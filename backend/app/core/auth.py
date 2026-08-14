from __future__ import annotations

import hashlib
import hmac

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import Child, ParentUser

settings = get_settings()


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(f"{settings.app_secret_key}:{raw_token}".encode("utf-8")).hexdigest()


async def require_parent_auth(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ParentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    raw_token = authorization.split(" ", 1)[1].strip()
    token_hash = hash_token(raw_token)

    result = await db.execute(select(ParentUser).where(ParentUser.auth_token_hash == token_hash))
    parent = result.scalars().first()
    if not parent:
        raise HTTPException(status_code=401, detail="Invalid parent token")
    return parent


async def require_admin(parent: ParentUser = Depends(require_parent_auth)) -> ParentUser:
    if not parent.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return parent


async def require_kid_auth(
    request: Request,
    x_household_code: str | None = Header(default=None),
    x_child_pin: str | None = Header(default=None),
    x_child_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    if x_household_code and hmac.compare_digest(x_household_code, settings.household_code):
        return

    if x_child_pin and x_child_id:
        child = await db.get(Child, x_child_id)
        if child and child.kid_pin_hash and hmac.compare_digest(hash_token(x_child_pin), child.kid_pin_hash):
            return

    raise HTTPException(status_code=401, detail="Invalid kid credentials")
