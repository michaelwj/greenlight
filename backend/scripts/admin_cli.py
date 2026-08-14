from __future__ import annotations

import argparse
import asyncio
import base64
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.auth import hash_token
from app.db.session import SessionLocal
from app.models.entities import Child, ParentUser, YoutubeRequest


def generate_vapid_keys() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    def b64url(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print("Add these to backend/.env:")
    print(f"VAPID_PRIVATE_KEY={b64url(private_raw)}")
    print(f"VAPID_PUBLIC_KEY={b64url(public_raw)}")
    print("VAPID_SUBJECT=mailto:you@example.com")


async def create_parent(name: str, email: str, admin: bool) -> None:
    token = secrets.token_urlsafe(32)
    async with SessionLocal() as session:
        parent = ParentUser(name=name, email=email, auth_token_hash=hash_token(token), is_admin=admin)
        session.add(parent)
        await session.commit()
        await session.refresh(parent)
    print(f"Created parent {parent.id} ({email})")
    print(f"Bearer token (save it now, it is not stored in plaintext): {token}")


async def rotate_parent_token(email: str) -> None:
    token = secrets.token_urlsafe(32)
    async with SessionLocal() as session:
        result = await session.execute(select(ParentUser).where(ParentUser.email == email))
        parent = result.scalars().first()
        if not parent:
            raise SystemExit(f"No parent with email {email}")
        parent.auth_token_hash = hash_token(token)
        await session.commit()
    print(f"New bearer token for {email}: {token}")


async def create_child(display_name: str, pin: str | None) -> None:
    async with SessionLocal() as session:
        child = Child(display_name=display_name, kid_pin_hash=hash_token(pin) if pin else None)
        session.add(child)
        await session.commit()
        await session.refresh(child)
    print(f"Created child {child.id} ({display_name})")


async def submit_test_youtube_request(child_id: str, youtube_url: str) -> None:
    async with SessionLocal() as session:
        req = YoutubeRequest(
            requested_by_child_id=child_id,
            youtube_url=youtube_url,
            status="submitted",
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
    print(f"Created YouTube request {req.id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Greenlight admin tools")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate-vapid-keys")

    cp = sub.add_parser("create-parent")
    cp.add_argument("name")
    cp.add_argument("email")
    cp.add_argument("--admin", action="store_true", default=True)

    rt = sub.add_parser("rotate-parent-token")
    rt.add_argument("email")

    cc = sub.add_parser("create-child")
    cc.add_argument("display_name")
    cc.add_argument("--pin")

    t = sub.add_parser("submit-test-youtube-request")
    t.add_argument("child_id")
    t.add_argument("youtube_url")

    return parser


async def run() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate-vapid-keys":
        generate_vapid_keys()
    elif args.command == "create-parent":
        await create_parent(args.name, args.email, args.admin)
    elif args.command == "rotate-parent-token":
        await rotate_parent_token(args.email)
    elif args.command == "create-child":
        await create_child(args.display_name, args.pin)
    elif args.command == "submit-test-youtube-request":
        await submit_test_youtube_request(args.child_id, args.youtube_url)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    asyncio.run(run())
