from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .core.config import settings
from .core.database import initialize_database
from .services.document_service import DocumentService
from .services.graph_service import GraphService
from .services.pageindex_service import PageIndexService


app = FastAPI(
    title="Anton Rx Track API",
    version="0.1.0",
    description="Local-first medical benefit policy tracker for hackathon execution.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup() -> None:
    settings.ensure_directories()
    initialize_database(settings.sqlite_path)
    GraphService().initialize_schema()
    documents = DocumentService().refresh_documents()
    PageIndexService().start_default_warmup(documents)


app.include_router(router, prefix="/api")
