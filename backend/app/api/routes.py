from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..models.schemas import (
    AskRequest,
    AskResponse,
    ChangeRequest,
    ChangeResponse,
    CompareRequest,
    CompareResponse,
    DocumentSummary,
    EvidenceSummaryRequest,
    EvidenceSummaryResponse,
    GraphStatus,
    HistoryDetailResponse,
    HistoryDeleteResponse,
    IndexBuildRequest,
    IndexBuildResponse,
    IndexSettingsResponse,
    IndexSettingsUpdateRequest,
    RequestHistoryEntry,
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
history_repository = policy_service.repository


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/graph/status", response_model=GraphStatus)
def graph_status() -> GraphStatus:
    return graph_service.get_status()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents() -> list[DocumentSummary]:
    return document_service.refresh_documents()


@router.get("/documents/{doc_id}/pdf")
def get_document_pdf(doc_id: str) -> FileResponse:
    document = document_service.get_document(doc_id)
    pdf_path = Path(document.path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found.")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type="inline",
    )


@router.get("/history", response_model=list[RequestHistoryEntry])
def list_history(kind: str | None = None, limit: int = 50) -> list[RequestHistoryEntry]:
    return history_repository.list_request_history(kind=kind, limit=limit)


@router.get("/history/{history_id}", response_model=HistoryDetailResponse)
def get_history(history_id: str) -> HistoryDetailResponse:
    history_entry = history_repository.get_request_history(history_id)
    if not history_entry:
        raise HTTPException(status_code=404, detail="History entry not found.")
    return history_entry


@router.delete("/history", response_model=HistoryDeleteResponse)
def clear_history() -> HistoryDeleteResponse:
    deleted = history_repository.clear_request_history()
    return HistoryDeleteResponse(deleted=deleted, message=f"Cleared {deleted} history entries.")


@router.delete("/history/{history_id}", response_model=HistoryDeleteResponse)
def delete_history(history_id: str) -> HistoryDeleteResponse:
    deleted = history_repository.delete_request_history(history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="History entry not found.")
    return HistoryDeleteResponse(deleted=1, message="Deleted history entry.")


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


@router.post("/evidence/summary", response_model=EvidenceSummaryResponse)
def summarize_evidence(payload: EvidenceSummaryRequest) -> EvidenceSummaryResponse:
    document = document_service.get_document(payload.doc_id)
    summary, source_method = policy_service.openai_service.summarize_evidence(
        document=document,
        page=payload.page,
        section=payload.section,
        snippet=payload.snippet,
        question=payload.question,
    )
    return EvidenceSummaryResponse(
        doc_id=document.doc_id,
        page=payload.page,
        section=payload.section,
        pdf_url=f"/api/documents/{document.doc_id}/pdf#page={payload.page}",
        summary=summary,
        source_method=source_method,
    )


@router.post("/ask", response_model=AskResponse)
def ask_policy(payload: AskRequest) -> AskResponse:
    return policy_service.answer_question(payload)


@router.post("/compare", response_model=CompareResponse)
def compare_policies(payload: CompareRequest) -> CompareResponse:
    return comparison_service.compare(payload)


@router.post("/changes", response_model=ChangeResponse)
def compare_changes(payload: ChangeRequest) -> ChangeResponse:
    return comparison_service.diff_versions(payload)
