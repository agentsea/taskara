import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://surf.agentlabs.xyz",
        "https://surf.dev.agentlabs.xyz",
        "https://surf.deploy.agentlabs.xyz",
        "https://surf.stg.agentlabs.xyz",
        "https://surf.testing.agentlabs.xyz",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)


@app.get("/")
async def root():
    return {"message": "tasks4lyfe"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app=app, host="0.0.0.0", port=8088)  # type: ignore
