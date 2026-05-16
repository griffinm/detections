from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .deps import engine, settings
from .routers import (
    classes,
    clips,
    detections,
    frames,
    labeling,
    metrics,
    models,
    settings as settings_r,
    stream,
    subclasses,
    system,
    training,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="video-detection", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    frames_dir = str(settings.frames_dir)
    try:
        app.mount("/files/frames", StaticFiles(directory=frames_dir), name="frames")
    except RuntimeError:
        pass  # directory may not exist yet in test environments

    for router in (
        clips,
        frames,
        detections,
        classes,
        subclasses,
        labeling,
        models,
        training,
        metrics,
        settings_r,
        system,
        stream,
    ):
        app.include_router(router.router, prefix="/api")

    return app


app = create_app()
