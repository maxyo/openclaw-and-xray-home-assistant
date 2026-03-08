#!/usr/bin/env python3
"""Generate sing-box config from a VLESS URI.

Supports two common URI styles:
1) Standard: vless://<uuid>@<host>:<port>?...
2) Base64 userinfo/netloc style often used by share links:
   vless://<base64(auto:<uuid>@<host>:<port>)>?...

Supported transport mappings: tcp/ws/grpc/http/httpupgrade.
Supported security mappings: none/tls/reality.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


def _last(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    if not values:
        return default
    return values[-1]


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _b64_decode(value: str) -> str:
    raw = value.strip()
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding).decode("utf-8", errors="strict")


def _parse_host_port(raw: str) -> tuple[str, int]:
    value = raw.strip()
    if not value:
        raise ValueError("host:port is empty")

    # IPv6 literal in brackets: [2001:db8::1]:443
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            raise ValueError("invalid IPv6 host format")
        host = value[1:end]
        port = 443
        rest = value[end + 1 :]
        if rest.startswith(":"):
            try:
                port = int(rest[1:])
            except ValueError as exc:
                raise ValueError("invalid port in host:port") from exc
        return host, port

    if ":" in value:
        host, port_raw = value.rsplit(":", 1)
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError("invalid port in host:port") from exc
        return host, port

    return value, 443


def _decode_share_target(parsed) -> tuple[str, str, int]:
    """Return (uuid, host, port) from parsed VLESS URL."""
    if parsed.username and parsed.hostname:
        uuid = unquote(parsed.username)
        host = parsed.hostname
        port = int(parsed.port or 443)
        return uuid, host, port

    # Some providers place a base64 blob in netloc/path
    token = (parsed.netloc or "").strip()
    if not token and parsed.path:
        token = parsed.path.lstrip("/").strip()

    if not token:
        raise ValueError("proxy_vless_uri is missing UUID/user part")

    decoded = token
    if "@" not in decoded:
        try:
            decoded = _b64_decode(token)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "proxy_vless_uri has no user@host and base64 decode failed"
            ) from exc

    if "@" not in decoded:
        raise ValueError("proxy_vless_uri decoded payload must contain user@host")

    user_part, host_part = decoded.split("@", 1)
    user_part = user_part.strip()
    if not user_part:
        raise ValueError("proxy_vless_uri is missing UUID/user part")

    # Formats observed in the wild:
    # - <uuid>
    # - auto:<uuid>
    # - user:pass:<uuid> (take the right-most segment as UUID candidate)
    uuid = user_part.split(":")[-1].strip()
    if not uuid:
        raise ValueError("proxy_vless_uri is missing UUID/user part")

    host, port = _parse_host_port(host_part)
    if not host:
        raise ValueError("proxy_vless_uri is missing host")

    return uuid, host, port


def build_vless_outbound(uri: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "vless":
        raise ValueError("proxy_vless_uri must start with vless://")

    uuid, host, port = _decode_share_target(parsed)

    query = parse_qs(parsed.query, keep_blank_values=True)

    outbound: dict[str, Any] = {
        "type": "vless",
        "tag": "proxy",
        "server": host,
        "server_port": int(port or 443),
        "uuid": uuid,
    }

    flow = _last(query, "flow")
    if flow:
        outbound["flow"] = flow

    packet_encoding = _last(query, "packetEncoding") or _last(query, "packet_encoding")
    if packet_encoding:
        outbound["packet_encoding"] = packet_encoding

    # Xray-compatible aliases:
    # - security=tls/reality
    # - tls=1 as TLS enable flag
    # - peer as SNI alias
    security = (_last(query, "security") or "").strip().lower()
    has_reality_keys = bool(_last(query, "pbk") or _last(query, "publicKey"))
    if not security:
        if has_reality_keys:
            security = "reality"
        elif _truthy(_last(query, "tls")):
            security = "tls"

    if security in {"tls", "reality"}:
        tls: dict[str, Any] = {"enabled": True}

        server_name = _last(query, "sni") or _last(query, "peer") or _last(query, "host")
        if server_name:
            tls["server_name"] = server_name

        alpn = _last(query, "alpn")
        if alpn:
            tls["alpn"] = _split_csv(alpn)

        if _truthy(_last(query, "allowInsecure") or _last(query, "insecure")):
            tls["insecure"] = True

        fingerprint = _last(query, "fp") or _last(query, "fingerprint")
        if security == "reality" and not fingerprint:
            # sing-box requires uTLS for reality connections.
            fingerprint = "chrome"
        if fingerprint:
            tls["utls"] = {"enabled": True, "fingerprint": fingerprint}

        if security == "reality":
            reality: dict[str, Any] = {"enabled": True}
            public_key = _last(query, "pbk") or _last(query, "publicKey")
            short_id = _last(query, "sid") or _last(query, "shortId")
            if not public_key:
                raise ValueError("security=reality requires pbk/publicKey")
            reality["public_key"] = public_key
            if short_id:
                reality["short_id"] = short_id
            tls["reality"] = reality

        outbound["tls"] = tls
    elif security and security not in {"none"}:
        raise ValueError(f"unsupported security={security!r}; expected none|tls|reality")

    transport = (_last(query, "type") or _last(query, "network") or "tcp").strip().lower()
    if transport and transport not in {"tcp", "none"}:
        transport_config: dict[str, Any] = {}

        if transport in {"ws", "websocket"}:
            transport_config["type"] = "ws"
            path = _last(query, "path")
            if path:
                transport_config["path"] = unquote(path)
            host_header = _last(query, "host")
            if host_header:
                transport_config["headers"] = {"Host": host_header}
        elif transport == "grpc":
            transport_config["type"] = "grpc"
            service_name = _last(query, "serviceName") or _last(query, "service_name")
            if service_name:
                transport_config["service_name"] = service_name
        elif transport == "http":
            transport_config["type"] = "http"
            host_header = _last(query, "host")
            path = _last(query, "path")
            if host_header:
                transport_config["host"] = _split_csv(host_header)
            if path:
                transport_config["path"] = unquote(path)
        elif transport == "httpupgrade":
            transport_config["type"] = "httpupgrade"
            host_header = _last(query, "host")
            path = _last(query, "path")
            if host_header:
                transport_config["host"] = host_header
            if path:
                transport_config["path"] = unquote(path)
        else:
            raise ValueError(
                f"unsupported transport type={transport!r}; expected tcp|ws|grpc|http|httpupgrade"
            )

        outbound["transport"] = transport_config

    return outbound


def build_config(vless_uri: str, listen_port: int, log_level: str) -> dict[str, Any]:
    proxy_outbound = build_vless_outbound(vless_uri)
    return {
        "log": {
            "level": log_level,
            "timestamp": True,
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": int(listen_port),
            }
        ],
        "outbounds": [
            proxy_outbound,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rules": [
                {"ip_is_private": True, "outbound": "direct"},
            ],
            "final": "proxy",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate sing-box config from VLESS URI")
    parser.add_argument("--vless-uri", required=True, help="VLESS share URI")
    parser.add_argument("--listen-port", type=int, default=17890, help="Local mixed proxy port")
    parser.add_argument("--log-level", default="warn", help="sing-box log level")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.listen_port < 1 or args.listen_port > 65535:
        raise ValueError("listen-port must be 1..65535")

    config = build_config(
        vless_uri=args.vless_uri,
        listen_port=args.listen_port,
        log_level=args.log_level,
    )
    json.dump(config, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[vless_to_singbox] error: {exc}", file=sys.stderr)
        raise
