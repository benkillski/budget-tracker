from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import engine, init_db
from app.scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler(settings, engine)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Budget Tracker", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
