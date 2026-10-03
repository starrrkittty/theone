from fastapi import FastAPI

from app.routers import router
from app.engine import experts_catalog
from app.group_adapters import group_e_contract
from app.mobile import router as mobile_router

app = FastAPI(
    title="AI Fitness Coach - B Group Service",
    version="0.1.0",
    description="Validated movement feedback and planning APIs for the B-group prototype.",
)
app.include_router(router, prefix="/api/v1")
app.include_router(mobile_router, prefix="/api")


@app.get("/api/v1/integration/group-e")
def group_e_integration_contract() -> dict[str, object]:
    return group_e_contract()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "b-group-coach"}
