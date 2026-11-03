from fastapi import FastAPI
from sqlalchemy import text

from .core.database import engine

app = FastAPI(
    title="Buddy-Gets API",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/database")
def database_health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return {"database": "connected"}