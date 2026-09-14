from fastapi import FastAPI

app = FastAPI(title="Budget Tracker")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
