#!/usr/bin/env bash
# Greenlight one-command setup.
# Checks prerequisites, builds your .env interactively, starts the stack,
# generates push keys, and creates your parent account and kids.
set -euo pipefail

cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

ask() { # ask "Prompt" default -> REPLY
  local prompt="$1" default="${2-}"
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " REPLY || true
    REPLY="${REPLY:-$default}"
  else
    read -r -p "$prompt: " REPLY || true
  fi
}

set_env() { # set_env KEY value  (in backend/.env)
  local key="$1" value="$2"
  if grep -q "^${key}=" backend/.env; then
    # portable in-place sed (GNU + BSD)
    sed -i.bak "s|^${key}=.*|${key}=${value//|/\\|}|" backend/.env && rm -f backend/.env.bak
  else
    printf '%s=%s\n' "$key" "$value" >> backend/.env
  fi
}

bold "Greenlight setup"
echo

# ---------- prerequisites ----------
command -v docker >/dev/null || die "Docker is required — install it from https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required (the 'docker compose' subcommand)"
docker info >/dev/null 2>&1 || die "Docker daemon not reachable — is it running, and is your user in the docker group?"

# ---------- .env ----------
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  note "Created backend/.env from the template."
fi

bold "1/5 — Core settings"
set_env APP_ENV prod
set_env APP_SECRET_KEY "$(head -c 32 /dev/urandom | base64 | tr -d '=+/' | head -c 43)"

household_default="$(shuf -i 100000-999999 -n 1 2>/dev/null || printf '%06d' $((RANDOM * RANDOM % 1000000)))"
ask "Household code (kids type this once on their device)" "$household_default"
set_env HOUSEHOLD_CODE "$REPLY"

tz_default="$(cat /etc/timezone 2>/dev/null || timedatectl show -p Timezone --value 2>/dev/null || echo America/Chicago)"
ask "Household timezone" "$tz_default"
set_env HOUSEHOLD_TIMEZONE "$REPLY"

# Postgres password lives in the compose-level .env
if [ ! -f .env ] || ! grep -q '^POSTGRES_PASSWORD=' .env 2>/dev/null; then
  pg_pass="$(head -c 24 /dev/urandom | base64 | tr -d '=+/' | head -c 32)"
  printf 'POSTGRES_PASSWORD=%s\n' "$pg_pass" >> .env
else
  pg_pass="$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
fi
set_env DATABASE_URL "postgresql+asyncpg://postgres:${pg_pass}@db:5432/greenlight"

ask "Port to serve Greenlight on" "8080"
grep -q '^API_PORT=' .env 2>/dev/null && sed -i.bak "s|^API_PORT=.*|API_PORT=$REPLY|" .env && rm -f .env.bak || printf 'API_PORT=%s\n' "$REPLY" >> .env
api_port="$REPLY"

echo
bold "2/5 — Plex"
note "Approved videos are downloaded into a folder your Plex library watches."
note "Plex is optional to start — you can fill these in later in backend/.env."
ask "Host folder for downloaded videos (created if missing)" "$PWD/media"
mkdir -p "$REPLY"
grep -q '^MEDIA_ROOT=' .env 2>/dev/null && sed -i.bak "s|^MEDIA_ROOT=.*|MEDIA_ROOT=$REPLY|" .env && rm -f .env.bak || printf 'MEDIA_ROOT=%s\n' "$REPLY" >> .env

ask "Plex server URL (e.g. http://192.168.1.20:32400, empty to skip)" ""
if [ -n "$REPLY" ]; then
  set_env PLEX_URL "$REPLY"
  ask "Plex token (docs/install.md explains how to find it)" ""
  set_env PLEX_TOKEN "$REPLY"
  ask "Plex library section id for that folder" ""
  set_env PLEX_LIBRARY_SECTION_ID "$REPLY"
fi

echo
bold "3/5 — AI screening"
note "The screener reads each video's transcript and metadata and decides:"
note "auto-approve, parent review, or deny. Without an API key everything"
note "simply goes to parent review — Greenlight still works."
ask "AI provider: 'openai', 'anthropic', or 'none'" "none"
case "$REPLY" in
  openai)
    set_env AI_PROVIDER api
    ask "OpenAI API key" ""
    set_env OPENAI_API_KEY "$REPLY"
    ask "Model" "gpt-4.1-mini"
    set_env AI_MODEL "$REPLY"
    ;;
  anthropic)
    set_env AI_PROVIDER anthropic
    ask "Anthropic API key" ""
    set_env ANTHROPIC_API_KEY "$REPLY"
    ask "Model" "claude-haiku-4-5"
    set_env AI_MODEL "$REPLY"
    ;;
  *)
    note "Skipping AI — every request will wait for parent review."
    ;;
esac

echo
bold "4/5 — Building and starting (first build takes a few minutes)"
docker compose up -d --build

note "Waiting for the API to come up..."
for i in $(seq 1 60); do
  if curl -fsS "http://localhost:${api_port}/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "http://localhost:${api_port}/health" >/dev/null 2>&1 || die "API did not become healthy — check 'docker compose logs api'"

# Web push keys (for parent notifications) — generated inside the container.
if ! grep -q '^VAPID_PUBLIC_KEY=.\+' backend/.env; then
  keys="$(docker compose exec -T api python scripts/admin_cli.py generate-vapid-keys)"
  set_env VAPID_PUBLIC_KEY "$(echo "$keys" | grep VAPID_PUBLIC_KEY | cut -d= -f2-)"
  set_env VAPID_PRIVATE_KEY "$(echo "$keys" | grep VAPID_PRIVATE_KEY | cut -d= -f2-)"
  docker compose up -d api worker scheduler
  note "Generated web-push keys."
fi

echo
bold "5/5 — Your family"
ask "Parent name" "Parent"
pname="$REPLY"
ask "Parent email" "parent@example.com"
docker compose exec -T api python scripts/admin_cli.py create-parent "$pname" "$REPLY" | tee /tmp/greenlight-parent.txt
echo
note "^ SAVE THE BEARER TOKEN — it is how you sign in to the parent app."
while true; do
  ask "Add a kid (name, empty to finish)" ""
  [ -z "$REPLY" ] && break
  docker compose exec -T api python scripts/admin_cli.py create-child "$REPLY"
done

echo
bold "Done!"
host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
note "Kid portal:  http://${host_ip:-localhost}:${api_port}/kid/"
note "Parent app:  http://${host_ip:-localhost}:${api_port}/parent/  (sign in with the bearer token above)"
note "Config:      backend/.env  (apply changes with: docker compose up -d)"
note "Next steps:  docs/install.md covers Plex library setup and iPhone home-screen install."
