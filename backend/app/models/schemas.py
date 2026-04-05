from typing import Any

from pydantic import BaseModel, Field


class EvidenceSnippet(BaseModel):
    page: int
    section: str = "unknown"
    snippet: str
    retrieval_method: str = "keyword_fallback"


class DocumentSummary(BaseModel):
    doc_id: str
    payer: str
    policy_name: str
    path: str
    version_label: str = "current"
    document_pattern: str
    likely_drug: str | None = None
    version_group: str | None = None


class DocumentUploadResponse(BaseModel):
    stored_filename: str
    path: str
    duplicate: bool = False
    message: str
    document: DocumentSummary | None = None


class RequestHistoryEntry(BaseModel):
    history_id: str
    kind: str
    title: str
    summary: str
    status: str
    question: str
    drug_name: str
    payer_filters: list[str] = Field(default_factory=list)
    old_doc_id: str | None = None
    new_doc_id: str | None = None
    created_at: str


class HistoryDetailResponse(RequestHistoryEntry):
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)


class HistoryDeleteResponse(BaseModel):
    deleted: int
    message: str


class IndexBuildRequest(BaseModel):
    doc_ids: list[str] | None = None
    force: bool = False


class IndexBuildResult(BaseModel):
    doc_id: str
    status: str
    detail: str
    index_dir: str


class IndexBuildResponse(BaseModel):
    results: list[IndexBuildResult]


class IndexSettingsUpdateRequest(BaseModel):
    enabled: bool


class IndexSettingsResponse(BaseModel):
    enabled: bool
    running: bool
    detail: str


class EvidenceSummaryRequest(BaseModel):
    doc_id: str
    page: int
    section: str
    snippet: str
    question: str | None = None


class EvidenceSummaryResponse(BaseModel):
    doc_id: str
    page: int
    section: str
    pdf_url: str
    summary: str
    source_method: str


class AskRequest(BaseModel):
    drug_name: str
    question: str
    payer_filters: list[str] = Field(default_factory=list)
    top_k: int = 3


class GraphContext(BaseModel):
    enabled: bool = False
    persisted: bool = False
    status_message: str = "Neo4j not configured."
    known_payers_for_drug: list[str] = Field(default_factory=list)
    known_versions_for_policy: list[str] = Field(default_factory=list)
    indications_in_graph: list[str] = Field(default_factory=list)
    requirement_types: list[str] = Field(default_factory=list)
    related_biosimilars: list[str] = Field(default_factory=list)
    evidence_count: int = 0


class PolicyRecord(BaseModel):
    doc_id: str
    payer: str
    policy_name: str
    document_pattern: str
    effective_date: str = "unknown"
    drug_name_brand: str
    drug_name_generic: str = "unknown"
    drug_category: str = "unknown"
    access_status: str = "unknown"
    preferred_status_rank: str = "unknown"
    covered_indications: list[str] = Field(default_factory=list)
    coverage_status: str = "unknown"
    prior_auth_required: str = "unknown"
    prior_auth_criteria: str = "unknown"
    step_therapy: str = "unknown"
    site_of_care: str = "unknown"
    dosing_quantity_limits: str = "unknown"
    hcpcs_codes: list[str] = Field(default_factory=list)
    biosimilar_reference_relationships: list[str] = Field(default_factory=list)
    confidence: str = "low"
    status: str = "Partial"
    answer: str = "No answer generated."
    evidence: list[EvidenceSnippet] = Field(default_factory=list)
    source_method: str = "keyword_fallback"
    graph_context: GraphContext | None = None


class AskResponse(BaseModel):
    records: list[PolicyRecord]


class CompareRequest(BaseModel):
    drug_name: str
    question: str = "How do these payers cover this drug?"
    payer_filters: list[str] = Field(default_factory=list)
    top_k: int = 3


class CompareRow(BaseModel):
    payer: str
    policy_name: str
    drug: str
    coverage: str
    prior_auth: str
    step_therapy: str
    site_of_care: str
    effective_date: str
    access_status: str
    confidence: str
    status: str


class GraphCompareSummary(BaseModel):
    enabled: bool = False
    status_message: str = "Neo4j not configured."
    payer_count: int = 0
    payer_names: list[str] = Field(default_factory=list)
    coverage_status_counts: dict[str, int] = Field(default_factory=dict)
    prior_auth_counts: dict[str, int] = Field(default_factory=dict)
    step_therapy_counts: dict[str, int] = Field(default_factory=dict)
    site_of_care_restriction_count: int = 0


class CompareResponse(BaseModel):
    rows: list[CompareRow]
    records: list[PolicyRecord]
    graph_summary: GraphCompareSummary | None = None


class ChangeRequest(BaseModel):
    drug_name: str
    old_doc_id: str
    new_doc_id: str
    question: str = "What changed between these policy versions?"


class DiffEntry(BaseModel):
    field: str
    old_value: Any
    new_value: Any
    change_type: str


class GraphChangeSummary(BaseModel):
    enabled: bool = False
    status_message: str = "Neo4j not configured."
    added_indications: list[str] = Field(default_factory=list)
    removed_indications: list[str] = Field(default_factory=list)
    added_requirement_types: list[str] = Field(default_factory=list)
    removed_requirement_types: list[str] = Field(default_factory=list)
    summary: str = "Graph comparison unavailable."


class GraphStatus(BaseModel):
    configured: bool
    connected: bool
    detail: str


class ChangeResponse(BaseModel):
    old_record: PolicyRecord
    new_record: PolicyRecord
    diffs: list[DiffEntry]
    graph_summary: GraphChangeSummary | None = None
    narrative_summary: str = "No change summary generated."
