"""FastAPI application entry point."""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.responses import FileResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / ".deps"))
sys.path.insert(0, str(PROJECT_ROOT / "coach"))

from config.settings import settings
from api.routes import router as api_router
from api.upload import router as upload_router
from api.yoga_routes import router as yoga_router
from app.routers import router as coach_router
from api.coach_bridge import router as coach_bridge_router
from api.perception_routes import router as perception_router
from api.set_routes import router as set_router
from app.mobile import router as mobile_router


# Configure detection logging.
# - 'detect' logger emits INFO events (state transitions, exercise switches,
#   reps, sessions) always — these surface in Render's runtime logs.
# - DEBUG per-frame lines only when DETECTION_DEBUG_LOG=true.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
))
_detect_logger = logging.getLogger("detect")
_detect_logger.handlers = [_handler]
_detect_logger.setLevel(
    logging.DEBUG if settings.DETECTION_DEBUG_LOG else logging.INFO
)
_detect_logger.propagate = False


# Create FastAPI app
app = FastAPI(
    title="AI Fitness Coach - Agent A API",
    description=(
        "Automatic exercise recognition, kinematic analysis, and structured "
        "action reports for the AI fitness coach"
    ),
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=settings.EFFECTIVE_CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix="/api")
app.include_router(set_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(yoga_router, prefix="/api")
app.include_router(coach_router, prefix="/api")
app.include_router(coach_bridge_router, prefix="/api")
app.include_router(perception_router, prefix="/api")
app.include_router(mobile_router, prefix="/api")


@app.get("/coach")
def coach_console():
    return FileResponse(PROJECT_ROOT / "coach" / "index.html")

# Mount uploads directory for serving videos
uploads_path = Path(settings.UPLOAD_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")


@app.get("/")
async def root():
    """Root endpoint."""
    built_frontend = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    if built_frontend.exists():
        return FileResponse(built_frontend)
    return await service_info()


@app.get("/api/service-info")
async def service_info():
    return {
        "name": "AI Fitness Coach - Agent A API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/health",
        "modes": {
            "exercise": {
                "websocket": "/api/ws/pose/{client_id}",
                "catalog": "/api/exercises",
                "health": "/api/health",
            },
            "yoga": {
                "websocket": "/api/ws/yoga/{client_id}",
                "catalog": "/api/yoga/poses",
                "health": "/api/yoga/health",
            },
        },
    }


frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
