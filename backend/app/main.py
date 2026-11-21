from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .core.config import get_settings
from .database.models import Base
from .database.session import get_engine


def create_app(create_tables: bool = True) -> FastAPI:
    app = FastAPI(title="ParkiScribe API", version="0.1.0",
                  description="Assistive air-writing research platform. Not a diagnostic system.")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    if create_tables:
        Base.metadata.create_all(get_engine())   # dev convenience; production uses Alembic (migrations pending)
    return app


app = create_app()
