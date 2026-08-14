from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog


async def write_audit_log(
    session: AsyncSession,
    actor_type: str,
    action: str,
    target_type: str,
    actor_id: str | None = None,
    target_id: str | None = None,
    metadata_json: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata_json,
        )
    )
