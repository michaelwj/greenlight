# Security model

Greenlight is designed for **LAN-only deployment inside a household**. Read
this before exposing it any further.

## Trust model

- **Parent app**: bearer-token auth. Tokens are 256-bit random values, stored
  only as SHA-256 hashes; rotate with the admin CLI.
- **Kid portal**: household-code auth (`X-Household-Code` header). This is
  deliberately lightweight — it identifies the household, not the kid, and the
  kid picks their own name. The threat model is "kids should not need
  passwords," not "kids are adversaries." A kid could request videos as a
  sibling; screening and parent review still apply either way.
- **Admin actions** (creating parents/kids) happen via the CLI inside the
  container, not over the network.

## Recommendations

- Keep Greenlight reachable **only on your LAN** (the default compose file
  publishes one port on your host, nothing else). If you want remote parent
  access, prefer a VPN (WireGuard/Tailscale) over port forwarding.
- If you must expose it publicly, put it behind a reverse proxy with TLS
  (Caddy/Traefik/nginx) **and** an additional auth layer (e.g. forward-auth)
  for `/parent/`, and understand that the kid portal's household code is not
  designed to resist internet-scale attacks.
- Postgres and Redis are not published to the host and are reachable only on
  the compose network.
- Secrets live in `backend/.env` and the repo-root `.env` — both are
  gitignored. Never commit them.

## What Greenlight sends off-box

- **YouTube**: metadata/transcript fetches and video downloads (via yt-dlp).
- **Your AI provider** (only if configured): video title, channel,
  description, tags, and transcript text for screening. No kid names.
- **Plex**: library refresh + label calls on your LAN.
- **Web push**: notification payloads go through the browser push services
  (encrypted; standard Web Push).

Nothing else. There is no telemetry, no analytics, no phone-home.
