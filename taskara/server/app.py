import logging.config
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .router.benchmarks import router as benchmarks_router
from .router.tasks import router as tasks_router

logging.config.fileConfig("logging.conf", disable_existing_loggers=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("initializing boot sequence...")
    print("boot sequence initialized.")
    yield


app = FastAPI(lifespan=lifespan)

access_logger = logging.getLogger("access")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        msg = {"field": field, "message": error["msg"], "type": error["type"]}
        print("\n\n!error: ", msg, "\nrequest data: ", str(request.body()), "\n")
        access_logger.error(
            f"Validation error for field {field}: {error['msg']} (type: {error['type']}, request data: {str(request.body())})"
        )
        errors.append(msg)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": errors}
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    access_logger.info(f"Received request: {request.method} {request.url}")
    response = await call_next(request)
    access_logger.info(
        f"Returned response {request.method} {request.url}: {response.status_code}"
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(benchmarks_router)


@app.get("/")
async def root():
    return {"message": "A Taskara tracker"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("TASK_SERVER_PORT", "9070"))
    reload = os.getenv("TASK_SERVER_RELOAD", "false") == "true"

    uvicorn.run(app="taskara.server.app:app", host="0.0.0.0", port=port, reload=reload)
