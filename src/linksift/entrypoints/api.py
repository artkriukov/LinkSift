from fastapi import FastAPI

app = FastAPI(title="LinkSift", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    # Liveness only; does not assert external providers or the pipeline are ready.
    return {"status": "ok", "service": "linksift-api"}
