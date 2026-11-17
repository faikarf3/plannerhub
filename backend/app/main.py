from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.actions import ActionError
from app.deps import require_token
from app.routers import log, misc, tasks, time

app = FastAPI(title="Planner Hub")


@app.exception_handler(ActionError)
def _action_error(_: Request, exc: ActionError) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"ok": True}


for r in (log.router, tasks.router, time.router, misc.router):
    app.include_router(r, dependencies=[Depends(require_token)])
