from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import engine, init_db
from app.routers import dashboard, rules, settings as settings_router, transactions, trends
from app.scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler(settings, engine)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Budget Tracker", lifespan=lifespan)
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(rules.router)
app.include_router(trends.router)
app.include_router(settings_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
