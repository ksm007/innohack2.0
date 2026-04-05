from fastapi import APIRouter

from ..models.schemas import (
    AskRequest,
    AskResponse,
    ChangeRequest,
    ChangeResponse,
    CompareRequest,
    CompareResponse,
    DocumentSummary,
    GraphStatus,
    IndexBuildRequest,
    IndexBuildResponse,
    IndexSettingsResponse,
    IndexSettingsUpdateRequest,
)
from ..services.comparison_service import ComparisonService
from ..services.document_service import DocumentService
from ..services.graph_service import GraphService
from ..services.pageindex_service import PageIndexService
from ..services.policy_service import PolicyService


router = APIRouter()

document_service = DocumentService()
pageindex_service = PageIndexService()
graph_service = GraphService()
policy_service = PolicyService(
    document_service=document_service,
    pageindex_service=pageindex_service,
    graph_service=graph_service,
)
comparison_service = ComparisonService(
    policy_service=policy_service,
    document_service=document_service,
    graph_service=graph_service,
)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/graph/status", response_model=GraphStatus)
def graph_status() -> GraphStatus:
    return graph_service.get_status()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents() -> list[DocumentSummary]:
    return document_service.refresh_documents()


@router.post("/index/build", response_model=IndexBuildResponse)
def build_indexes(payload: IndexBuildRequest) -> IndexBuildResponse:
    documents = document_service.refresh_documents()
    target_ids = set(payload.doc_ids or [doc.doc_id for doc in documents])
    selected_documents = [document for document in documents if document.doc_id in target_ids]
    results = pageindex_service.build_indexes(selected_documents, force=payload.force)
    return IndexBuildResponse(results=results)


@router.get("/index/settings", response_model=IndexSettingsResponse)
def get_index_settings() -> IndexSettingsResponse:
    enabled, running, detail = pageindex_service.get_warmup_status()
    return IndexSettingsResponse(enabled=enabled, running=running, detail=detail)


@router.post("/index/settings", response_model=IndexSettingsResponse)
def update_index_settings(payload: IndexSettingsUpdateRequest) -> IndexSettingsResponse:
    documents = document_service.refresh_documents()
    enabled, running, detail = pageindex_service.set_warmup_enabled(payload.enabled, documents)
    return IndexSettingsResponse(enabled=enabled, running=running, detail=detail)


@router.post("/ask", response_model=AskResponse)
def ask_policy(payload: AskRequest) -> AskResponse:
    return policy_service.answer_question(payload)


@router.post("/compare", response_model=CompareResponse)
def compare_policies(payload: CompareRequest) -> CompareResponse:
    return comparison_service.compare(payload)


@router.post("/changes", response_model=ChangeResponse)
def compare_changes(payload: ChangeRequest) -> ChangeResponse:
    return comparison_service.diff_versions(payload)
