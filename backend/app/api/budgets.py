from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_kid_auth, require_parent_auth
from app.db.session import get_db
from app.models.entities import Child, ParentUser
from app.schemas.budgets import BudgetStatusRead, BudgetUpdate
from app.services.budgets import BudgetService

router = APIRouter(prefix="/api/children", tags=["budgets"])


async def _status_read(db: AsyncSession, child_id: str, bucket: str) -> BudgetStatusRead:
    child = await db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    status = await BudgetService(db).status(child_id, bucket)
    return BudgetStatusRead(
        child_id=child_id,
        bucket=status.bucket,
        weekly_minutes=status.weekly_minutes,
        used_minutes=status.used_minutes,
        remaining_minutes=status.remaining_minutes,
    )


@router.get("/{child_id}/budget", response_model=BudgetStatusRead)
async def get_budget(
    child_id: str,
    bucket: str = "entertainment",
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> BudgetStatusRead:
    return await _status_read(db, child_id, bucket)


@router.put("/{child_id}/budget", response_model=BudgetStatusRead)
async def set_budget(
    child_id: str,
    payload: BudgetUpdate,
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> BudgetStatusRead:
    child = await db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    await BudgetService(db).set_weekly_minutes(child_id, payload.weekly_minutes, payload.bucket)
    return await _status_read(db, child_id, payload.bucket)


@router.get("/{child_id}/budget-status", response_model=BudgetStatusRead)
async def kid_budget_status(
    child_id: str,
    _: None = Depends(require_kid_auth),
    db: AsyncSession = Depends(get_db),
) -> BudgetStatusRead:
    return await _status_read(db, child_id, "entertainment")
