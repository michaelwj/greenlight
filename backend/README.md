# Greenlight Backend

FastAPI app serving the API and both web frontends, an RQ worker for
downloads, and a scheduler for subscriptions/cleanup/digest. See the
[root README](../README.md) for what Greenlight is and
[CONTRIBUTING.md](../CONTRIBUTING.md) for development setup.

Layout:

```
app/
├── api/        # FastAPI routers (kid + parent endpoints)
├── core/       # config (env-driven), auth, rate limiting, logging
├── db/         # async SQLAlchemy session + base
├── models/     # ORM entities
├── schemas/    # pydantic request/response models
├── services/   # budgets, channel rules, digest, notifications, cleanup, dispatch
├── workers/    # RQ download worker, scheduler jobs, queue helpers
└── youtube/    # screening pipeline, AI classifier, transcript fetch
scripts/
└── admin_cli.py            # parents, tokens, kids, VAPID keys
alembic/                    # migrations (run automatically on API start)
```
