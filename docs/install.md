# Installing Greenlight

Greenlight runs as a small Docker Compose stack (API + worker + scheduler +
PostgreSQL + Redis) on any always-on box on your LAN: a NAS, a mini PC, the
machine already running Plex — anything with Docker.

## 1. Prerequisites

- **Docker Engine with Compose v2** — `docker compose version` should work.
  Install: <https://docs.docker.com/engine/install/>
- **A Plex server** (optional but the whole point) — anywhere on your network.
- ~2 GB of disk for the stack, plus space for downloaded videos.

## 2. Run the wizard

```bash
git clone https://github.com/michaelwj/greenlight.git
cd greenlight
./setup.sh
```

The wizard walks through everything below and starts the stack. If you prefer
manual setup: copy `backend/.env.example` to `backend/.env`, create a repo-root
`.env` with `POSTGRES_PASSWORD=<random>` (and optionally `API_PORT`,
`MEDIA_ROOT`), then `docker compose up -d --build`.

**Save the parent bearer token the wizard prints** — it is your login for the
parent app. Rotate it any time with:
`docker compose exec api python scripts/admin_cli.py rotate-parent-token <email>`

## 3. Plex setup

Greenlight downloads videos into a folder (`MEDIA_ROOT`, default `./media`)
and tells Plex to rescan after each download.

1. **Create a Plex library** (type: *Other Videos* works well) pointing at the
   same folder Greenlight downloads into. If Plex runs in Docker too, mount
   the folder into the Plex container and add that path to the library.
2. **Find your Plex token** (`PLEX_TOKEN`): open any item in the Plex web app →
   ⋮ → *Get Info* → *View XML* — the `X-Plex-Token=` value is at the end of the
   URL. ([Plex's official guide](https://support.plex.tv/articles/204059436))
3. **Find the library section id** (`PLEX_LIBRARY_SECTION_ID`): visit
   `http://<plex>:32400/library/sections?X-Plex-Token=<token>` and read the
   `key` of your new library. It's a small number like `1` or `4`.
4. Put all three (`PLEX_URL`, `PLEX_TOKEN`, `PLEX_LIBRARY_SECTION_ID`) in
   `backend/.env` and run `docker compose up -d`.

Every downloaded video gets a **Plex label with the requesting kid's name**
(e.g. `alice`). Use labels to build per-kid collections, or restrict a managed
Plex account to only its own label (account → *Restrictions* → *Allowed
labels*) so each kid sees only their own approved videos.

## 4. AI screening

Without an AI key Greenlight is still fully functional — every request waits
for a parent decision. With one, the screener reads the transcript + metadata
and auto-approves clean educational content.

| Setting | OpenAI | Anthropic | Local/other |
|---|---|---|---|
| `AI_PROVIDER` | `api` | `anthropic` | `api` (OpenAI-compatible) or `command` |
| Key | `OPENAI_API_KEY` | `ANTHROPIC_API_KEY` | per your endpoint |
| `AI_MODEL` | `gpt-4.1-mini` | `claude-haiku-4-5` | your model name |
| `AI_BASE_URL` | (default) | — | e.g. `http://ollama:11434/v1` |

Policy knobs worth reading in `backend/.env.example`:

- `SENSITIVE_TOPICS` — plain-language topics that **never** auto-approve, even
  from trusted channels. Edit it to match your family's rules; the AI reads
  your list verbatim.
- `AI_CONFIDENCE_THRESHOLD`, `AUTO_APPROVE_ENTERTAINMENT`,
  `YOUTUBE_MAX_DURATION_SECONDS`, `SHORT_VIDEO_REVIEW_MINUTES`,
  `DAILY_REQUEST_LIMIT`, `DEFAULT_ENTERTAINMENT_WEEKLY_MINUTES`.

## 5. Phones and tablets

- **Parent app** (`/parent/`): it's an installable PWA. On iPhone: open in
  Safari → Share → *Add to Home Screen*. Then enable push notifications in
  the app's Settings tab to get review requests as they happen.
- **Kid portal** (`/kid/`): add to home screen the same way. Kids pick their
  name, enter the household code once, and paste YouTube links (tap **Share →
  Copy link** on the video).

## 6. Day-2 operations

```bash
docker compose logs -f api worker      # watch activity
docker compose up -d --build           # upgrade after git pull
docker compose exec api python scripts/admin_cli.py --help   # admin tools
docker compose exec db pg_dump -U postgres greenlight > backup.sql
```

Config changes: edit `backend/.env`, then `docker compose up -d`.

## Troubleshooting

- **Kid submits a link and it fails with "That doesn't look like a YouTube
  link"** — they pasted search-result text. Use Share → Copy link.
- **Downloads fail with 403/429** — YouTube rate limiting; Greenlight retries
  automatically with delays. Persistent failures on one video usually mean
  it's region/age-restricted.
- **"Video unavailable / restricted" during screening** — your network may
  force YouTube Restricted Mode (router "safe search" features). Exempt the
  Greenlight server's IP from that enforcement.
- **Videos won't play on some devices** — shouldn't happen (downloads prefer
  h264+AAC), but check `docker compose logs worker` for format fallbacks.
- **Forgot the parent token** — rotate it (see §2).
