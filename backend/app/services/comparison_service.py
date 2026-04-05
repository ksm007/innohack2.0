from ..models.schemas import (
    AskRequest,
    ChangeRequest,
    ChangeResponse,
    CompareRequest,
    CompareResponse,
    CompareRow,
    DiffEntry,
)
from .document_service import DocumentService
from .graph_service import GraphService
from .openai_service import OpenAIService
from .policy_service import PolicyService


MEANINGFUL_FIELDS = {
    "coverage_status",
    "prior_auth_required",
    "prior_auth_criteria",
    "step_therapy",
    "site_of_care",
    "covered_indications",
    "dosing_quantity_limits",
}

DIFF_EXCLUDED_FIELDS = {
    "doc_id",
    "payer",
    "policy_name",
    "evidence",
    "answer",
    "source_method",
    "graph_context",
    "confidence",
    "status",
}


class ComparisonService:
    def __init__(
        self,
        policy_service: PolicyService,
        document_service: DocumentService,
        graph_service: GraphService,
    ) -> None:
        self.policy_service = policy_service
        self.document_service = document_service
        self.graph_service = graph_service
        self.openai_service = OpenAIService()

    def compare(self, payload: CompareRequest) -> CompareResponse:
        ask_response = self.policy_service.answer_question(
            AskRequest(
                drug_name=payload.drug_name,
                question=payload.question,
                payer_filters=payload.payer_filters,
                top_k=payload.top_k,
            )
        )
        selected_records = self._select_compare_records(ask_response.records)
        rows = [
            CompareRow(
                payer=record.payer,
                policy_name=record.policy_name,
                drug=record.drug_name_brand,
                coverage=record.coverage_status,
                prior_auth=record.prior_auth_required,
                step_therapy=record.step_therapy,
                site_of_care=record.site_of_care,
                effective_date=record.effective_date,
                access_status=record.access_status,
                confidence=record.confidence,
                status=record.status,
            )
            for record in selected_records
        ]
        graph_summary = self.graph_service.summarize_records(selected_records)
        return CompareResponse(rows=rows, records=selected_records, graph_summary=graph_summary)

    def diff_versions(self, payload: ChangeRequest) -> ChangeResponse:
        old_document = self.document_service.get_document(payload.old_doc_id)
        new_document = self.document_service.get_document(payload.new_doc_id)
        extraction_question = (
            f"{payload.question} {self.policy_service.VERSION_COMPARE_HINT}"
        )

        old_record = self.policy_service.answer_for_document(
            old_document,
            payload.drug_name,
            extraction_question,
            retrieval_mode="version_compare",
        )
        new_record = self.policy_service.answer_for_document(
            new_document,
            payload.drug_name,
            extraction_question,
            retrieval_mode="version_compare",
        )

        diffs = []
        old_data = old_record.model_dump()
        new_data = new_record.model_dump()
        for field in sorted(set(old_data).intersection(new_data)):
            if field in DIFF_EXCLUDED_FIELDS:
                continue
            if self._normalize_for_diff(old_data[field]) == self._normalize_for_diff(new_data[field]):
                continue
            diffs.append(
                DiffEntry(
                    field=field,
                    old_value=old_data[field],
                    new_value=new_data[field],
                    change_type="meaningful" if field in MEANINGFUL_FIELDS else "cosmetic_admin",
                )
            )
        graph_summary = self.graph_service.summarize_changes(payload.old_doc_id, payload.new_doc_id)
        narrative_summary = self.openai_service.summarize_diff(old_record, new_record, diffs)
        return ChangeResponse(
            old_record=old_record,
            new_record=new_record,
            diffs=diffs,
            graph_summary=graph_summary,
            narrative_summary=narrative_summary,
        )

    def _normalize_for_diff(self, value):
        if isinstance(value, str):
            normalized = " ".join(value.split()).strip().lower()
            return normalized
        if isinstance(value, list):
            return sorted(self._normalize_for_diff(item) for item in value)
        if isinstance(value, dict):
            return {key: self._normalize_for_diff(item) for key, item in sorted(value.items())}
        return value

    def _select_compare_records(self, records):
        best_by_payer = {}
        for record in records:
            if record.payer == "Unknown":
                continue
            current = best_by_payer.get(record.payer)
            if current is None or self._compare_score(record) > self._compare_score(current):
                best_by_payer[record.payer] = record
        selected = [record for record in best_by_payer.values() if self._compare_score(record) >= 15]
        return sorted(selected, key=lambda record: record.payer)

    def _compare_score(self, record) -> int:
        score = 0
        policy_lower = record.policy_name.lower()
        if record.status == "Answered":
            score += 40
        elif record.status == "Partial":
            score += 10
        if record.coverage_status != "unknown":
            score += 12
        if record.prior_auth_required != "unknown":
            score += 10
        if record.covered_indications:
            score += min(10, len(record.covered_indications) * 2)
        if record.effective_date != "unknown":
            score += 6
        if record.document_pattern == "single_drug":
            score += 8
        if record.graph_context and record.graph_context.requirement_types:
            score += 4
        low_value_tokens = [
            "summary of change",
            "summary-of-change",
            "preferred-products",
            "preferred products",
            "opening ceremony",
            "policy updates",
        ]
        if any(token in policy_lower for token in low_value_tokens):
            score -= 30
        return score
