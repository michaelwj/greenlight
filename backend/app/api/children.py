from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin, require_parent_auth
from app.db.session import get_db
from app.models.entities import Child, ParentUser
from app.schemas.children import ChildCreate, ChildRead, ChildUpdate, RequestLimitUpdate

router = APIRouter(prefix="/api", tags=["children"])


@router.get("/children", response_model=list[ChildRead])
async def list_children(db: AsyncSession = Depends(get_db)) -> list[ChildRead]:
    result = await db.execute(select(Child).where(Child.is_active.is_(True)))
    return [ChildRead.model_validate(item) for item in result.scalars().all()]


@router.put("/children/{child_id}/request-limit", response_model=ChildRead)
async def set_request_limit(
    child_id: str,
    payload: RequestLimitUpdate,
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> ChildRead:
    child = await db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if payload.daily_request_limit is not None and payload.daily_request_limit < 0:
        raise HTTPException(status_code=422, detail="Limit must be 0 or more")

    child.daily_request_limit = payload.daily_request_limit
    await db.commit()
    await db.refresh(child)
    return ChildRead.model_validate(child)


@router.post("/admin/children", response_model=ChildRead)
async def create_child(
    payload: ChildCreate,
    _: ParentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ChildRead:
    child = Child(display_name=payload.display_name, kid_pin_hash=payload.kid_pin_hash)
    db.add(child)
    await db.commit()
    await db.refresh(child)
    return ChildRead.model_validate(child)


@router.patch("/admin/children/{child_id}", response_model=ChildRead)
async def patch_child(
    child_id: str,
    payload: ChildUpdate,
    _: ParentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ChildRead:
    child = await db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(child, key, value)

    await db.commit()
    await db.refresh(child)
    return ChildRead.model_validate(child)
