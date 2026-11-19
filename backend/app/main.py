import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from app.actions import ActionError
from app.deps import require_token
from app.routers import climbs, log, misc, pipelines, tasks, time

# App loggers ("planner.*") to stdout, which Cloud Run sends to Cloud Logging.
# Uvicorn configures its own loggers and doesn't propagate, so no duplicates.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Planner Hub")


# Every error body carries a human-readable `message`, the same key successful
# /log replies use, so a Shortcut's notification always has something to show.

@app.exception_handler(ActionError)
def _action_error(_: Request, exc: ActionError) -> JSONResponse:
    return JSONResponse({"detail": exc.message, "message": exc.message}, status_code=exc.status)


@app.exception_handler(HTTPException)
def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "request failed"
    return JSONResponse(
        {"detail": exc.detail, "message": message},
        status_code=exc.status_code, headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    parts = [f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in errors]
    return JSONResponse(
        {"detail": errors, "message": "bad request: " + "; ".join(parts)}, status_code=422
    )


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"ok": True}


for r in (log.router, tasks.router, time.router, climbs.router, pipelines.router, misc.router):
    app.include_router(r, dependencies=[Depends(require_token)])
# Pipelines post with their own keys; deps.pipeline_source checks them.
app.include_router(pipelines.ingest)
