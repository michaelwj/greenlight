from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/kid/")


def _mount_static(route: str, directory: str, name: str) -> None:
    path = Path(directory)
    if path.is_dir():
        app.mount(route, StaticFiles(directory=str(path), html=True), name=name)


_mount_static("/kid", settings.kid_web_dir, "kid-web")
_mount_static("/parent", settings.parent_web_dir, "parent-web")
