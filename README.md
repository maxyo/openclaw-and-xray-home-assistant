# OpenClaw Home Assistant Add-ons

This repository contains Home Assistant add-ons for OpenClaw.

## Add-ons

### clawdbot_gateway
OpenClaw Gateway for HA OS with SSH tunnel support for remote connections and optional built-in VLESS outbound proxy.

**Included tools:**
- **gog** — Google Workspace CLI (Gmail, Calendar, Drive, Contacts, Sheets, Docs). See [gogcli.sh](https://gogcli.sh)
- **gh** — GitHub CLI.

## Installation

1. Go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add this repository:
   ```
   https://github.com/ngutman/clawdbot-ha-addon
   ```
3. Find "OpenClaw Gateway" in the add-on store and install

## Configuration

| Option | Description |
|--------|-------------|
| `install_mode` | `package` (default, no build) or `source` (clone + build from repo) |
| `port` | Gateway WebSocket port (default: 18789) |
| `verbose` | Enable verbose logging |
| `repo_url` | OpenClaw source repository (source mode only) |
| `branch` | Branch to checkout (optional, source mode only) |
| `github_token` | GitHub token for private repos (source mode only) |
| `proxy_mode` | `off` (default) or `vless` to enable built-in outbound proxy |
| `proxy_vless_uri` | VLESS URI used by built-in sing-box client (`proxy_mode=vless`) |
| `proxy_listen_port` | Local proxy port inside add-on (default: `7890`) |
| `proxy_no_proxy` | Extra comma-separated hosts to bypass proxy |
| `ssh_port` | SSH server port for tunnel access (default: 2222) |
| `ssh_authorized_keys` | Public keys for SSH access |

## Links
- [OpenClaw](https://github.com/openclaw/openclaw)
- [gog CLI](https://gogcli.sh)
- [GitHub CLI](https://cli.github.com)
