import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..models.schemas import (
    AskRequest,
    AskResponse,
    ChangeRequest,
    ChangeResponse,
    CompareRequest,
    CompareResponse,
    DocumentSummary,
    DocumentUploadResponse,
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


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    original_name = file.filename or "uploaded.pdf"
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

    incoming_hash = hashlib.sha1(content).hexdigest()
    for existing_path in document_service.document_paths():
        digest = hashlib.sha1(existing_path.read_bytes()).hexdigest()
        if digest == incoming_hash:
            existing_doc = next(
                (doc for doc in document_service.refresh_documents() if Path(doc.path) == existing_path.resolve()),
                None,
            )
            return DocumentUploadResponse(
                stored_filename=existing_path.name,
                path=str(existing_path.resolve()),
                duplicate=True,
                message="An identical PDF already exists in docs. The existing document was kept.",
                document=existing_doc,
            )

    safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", original_name).strip() or "uploaded.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    target_path = _unique_docs_path(safe_name)
    target_path.write_bytes(content)

    documents = document_service.refresh_documents()
    uploaded_doc = next((doc for doc in documents if Path(doc.path) == target_path.resolve()), None)
    return DocumentUploadResponse(
        stored_filename=target_path.name,
        path=str(target_path.resolve()),
        duplicate=False,
        message="PDF uploaded successfully and saved into docs.",
        document=uploaded_doc,
    )


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


def _unique_docs_path(filename: str) -> Path:
    candidate = document_service.document_root() / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        next_candidate = candidate.with_name(f"{stem}-{index}{suffix}")
        if not next_candidate.exists():
            return next_candidate
        index += 1
