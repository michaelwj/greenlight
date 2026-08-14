from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_parent_auth
from app.db.session import get_db
from app.models.entities import ParentUser, WeeklyDigest
from app.services.digest import WeeklyDigestService

router = APIRouter(prefix="/api/digests", tags=["digests"])


def _read(digest: WeeklyDigest) -> dict:
    return {
        "id": digest.id,
        "week_start": digest.week_start.isoformat(),
        "week_end": digest.week_end.isoformat(),
        "payload": digest.payload_json,
        "created_at": digest.created_at.isoformat(),
    }


@router.get("")
async def list_digests(
    limit: int = Query(default=12, le=52),
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(WeeklyDigest).order_by(WeeklyDigest.created_at.desc()).limit(limit)
    )
    return [_read(item) for item in result.scalars().all()]


@router.get("/latest")
async def latest_digest(
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(WeeklyDigest).order_by(WeeklyDigest.created_at.desc()).limit(1))
    digest = result.scalars().first()
    if not digest:
        raise HTTPException(status_code=404, detail="No digest generated yet")
    return _read(digest)


@router.post("/generate")
async def generate_digest_now(
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    digest = await WeeklyDigestService(db).run()
    return _read(digest)
