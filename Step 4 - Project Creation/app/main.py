import os
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import LOG_DIR
from app.database import init_db
from app.auth import cleanup_expired_sessions
from app.disk_monitor import run_fifo_cleanup, run_retention_cleanup
from app.routes import auth, queries, history, admin, system, ai_tools, ai_analysis


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log = logging.getLogger("sqh")
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)

    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, "sqh.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)


async def background_tasks():
    """Periodic background loop for session cleanup, FIFO, and retention."""
    logger = logging.getLogger("sqh.background")
    while True:
        try:
            await asyncio.sleep(300)
            cleanup_expired_sessions()
            run_fifo_cleanup()
            run_retention_cleanup()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Background task error: %s", exc, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = logging.getLogger("sqh")
    from app.fast_json import BACKEND as _json_backend
    logger.info("S1 Query Hub starting up (json=%s)", _json_backend)
    init_db()
    task = asyncio.create_task(background_tasks())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("S1 Query Hub shutting down")


app = FastAPI(title="S1 Query Hub", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(queries.router)
app.include_router(history.router)
app.include_router(admin.router)
app.include_router(system.router)
app.include_router(ai_tools.router)
app.include_router(ai_analysis.router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)
