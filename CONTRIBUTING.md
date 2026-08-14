# Contributing to Greenlight

Thanks for helping make YouTube livable for families!

## Development setup

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"    # Python 3.12+
.venv/bin/python -m pytest tests -q                          # run tests
```

Or run the whole stack with live-reload:

```bash
docker compose -f docker-compose.dev.yml up --build
```

The dev compose uses `backend/.env.example` directly and mounts the source, so
edits to `backend/app`, `kid-web`, and `parent-web` apply immediately (API
reloads automatically).

## Guidelines

- **Tests**: `pytest` must pass; add coverage for behavior you add or change.
  Screening/pipeline changes especially — that's the safety-critical core.
- **Style**: `ruff` (config in `pyproject.toml`). Frontends are dependency-free
  vanilla JS/CSS by design — please don't introduce build steps or frameworks.
- **Migrations**: schema changes need an Alembic revision in
  `backend/alembic/versions/` (they run automatically on container start).
- **Scope**: Greenlight is a YouTube screening pipeline for a single
  household. Device management, network blocking, and multi-tenant features
  are out of scope.
- **Kid-facing text**: friendly, blame-free, and explains what to do next.
  Parent-facing decisions must always show their reasons.

## Reporting issues

Include `docker compose logs api worker` output around the problem and your
(secrets-redacted) config where relevant. For suspected screening mistakes,
include the video URL and the "why review?" reasons shown in the parent app.
