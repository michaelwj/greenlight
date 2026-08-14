# Greenlight

**A self-hosted, parent-screened YouTube pipeline for families.** Kids request
videos; Greenlight screens them (hard rules → transcript → AI → channel trust →
weekly budgets); clean educational content downloads automatically to your Plex
library; everything borderline goes to a parent for one-tap review — all
without ever putting the YouTube algorithm in front of your kids.

Built for households that block YouTube at the network or device level but
still want the *good parts* — piano tutorials, science explainers, maker
videos — to get through.

## How it works

```
Kid pastes a YouTube link ──► Screening pipeline ──► one of three outcomes
                                   │
     ┌─────────────────────────────┼──────────────────────────────┐
     ▼                             ▼                              ▼
 auto-approve                 parent review                   auto-deny
 (clean educational,          (one-tap Approve/Deny           (blocked channel,
  trusted channels)            in the parent web app,          Shorts, over budget,
     │                         with "why review?" reasons)     unsafe content)
     ▼                                                            │
 downloads via yt-dlp,                                            ▼
 SponsorBlock-stripped,                              kid sees a friendly reason
 h264/AAC for direct play
     │
     ▼
 lands in your Plex library,
 tagged with the kid's name
```

- **Kid portal** — no account, no algorithm: paste a link, see status and
  friendly reasons, re-request removed videos.
- **Parent app** — installable PWA with push notifications: review queue with
  AI summaries and explicit "why review?" reasons, history, per-kid weekly
  entertainment budgets and daily request limits, channel trust/block lists,
  channel subscriptions, weekly digest.
- **Screening** — hard rules (Shorts blocked, duration caps, age-restriction),
  AI classification of transcript + metadata with a configurable
  `SENSITIVE_TOPICS` list that never auto-approves, channel trust, weekly
  entertainment budgets, per-day request caps, short-video depth checks.
- **Downloads** — yt-dlp with SponsorBlock ad/promo stripping, Apple-friendly
  h264+AAC selection, polite rate limiting with progressive retry, embedded
  metadata, per-kid Plex labels (use them for Plex smart collections or
  sharing restrictions).

## Quick start

Requirements: Docker with Compose v2, and (optionally) a Plex server.

```bash
git clone https://github.com/michaelwj/greenlight.git
cd greenlight
./setup.sh
```

The wizard checks prerequisites, builds your config, starts the stack,
creates your parent account (save the printed bearer token — it's your login),
and adds your kids. Then:

- Kid portal: `http://<server>:8080/kid/`
- Parent app: `http://<server>:8080/parent/`

Full details, including Plex library setup and finding your Plex token, in
**[docs/install.md](docs/install.md)**.

## AI screening (optional but recommended)

Greenlight works without an AI key — every request just waits for parent
review. With a key, clean educational content auto-approves and unsafe content
auto-denies, with parents reviewing only the borderline middle. Supported:

- **OpenAI-compatible APIs** (`AI_PROVIDER=api`) — OpenAI, or any endpoint
  speaking the same protocol (Ollama, LM Studio, OpenRouter…)
- **Anthropic** (`AI_PROVIDER=anthropic`)
- **Shell command** (`AI_PROVIDER=command`) — pipe the screening prompt to any
  CLI you like

Screening a video costs a fraction of a cent with small models
(`gpt-4.1-mini`, `claude-haiku-4-5`). Setup in
[docs/install.md](docs/install.md#ai-screening).

## Philosophy

- **The parent is the authority.** AI screens; it never has the final word on
  anything borderline. Every "needs review" decision shows its reasons.
- **No algorithm.** Kids get exactly what they ask for, nothing else. No
  recommendations, no autoplay, no Shorts.
- **Friendly denials.** Kids always see *why* — "you're out of fun-video
  minutes this week" teaches more than a silent block.
- **Self-hosted and private.** Your requests, transcripts, and viewing history
  never leave your house (except the transcript text sent to your chosen AI
  provider for screening, if you enable one).

## Non-goals

Device screen-time enforcement, network-level blocking (pair Greenlight with
your router/DNS controls), multi-household hosting, and anything that requires
distributing downloaded content beyond your own household.

## A note on downloading

Greenlight downloads videos via [yt-dlp](https://github.com/yt-dlp/yt-dlp) for
private, household-only viewing. Download YouTube content at your discretion. 
This project is provided for personal, non-commercial family use; 
you are responsible for how you use it.

## Contributing & license

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under
the [GNU AGPL-3.0](LICENSE).
