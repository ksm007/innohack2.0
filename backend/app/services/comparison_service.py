import re

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
            ),
            record_history=False,
        )
        selected_records = self._select_compare_records(ask_response.records)
        rows = [
            CompareRow(
                payer=record.payer,
                policy_name=record.policy_name,
                drug=record.drug_name_brand,
                coverage=self._display_value(record, "coverage_status", fallback="not stated in snippets"),
                prior_auth=self._display_value(record, "prior_auth_required", fallback="not stated in snippets"),
                step_therapy=self._display_value(record, "step_therapy", fallback="not stated in snippets"),
                site_of_care=self._display_value(record, "site_of_care", fallback="not stated in snippets"),
                effective_date=self._display_value(record, "effective_date", fallback="not stated in snippets"),
                access_status=record.access_status,
                confidence=record.confidence,
                status=record.status,
            )
            for record in selected_records
        ]
        graph_summary = self.graph_service.summarize_records(selected_records)
        response = CompareResponse(rows=rows, records=selected_records, graph_summary=graph_summary)
        self.policy_service.repository.save_request_history(
            kind="compare",
            title="Coverage comparison",
            status=self._summarize_status([record.status for record in selected_records]),
            request_payload=payload.model_dump(),
            response_payload=response.model_dump(),
            summary=f"Compared {len(rows)} payer rows for {payload.drug_name}.",
        )
        return response

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
        response = ChangeResponse(
            old_record=old_record,
            new_record=new_record,
            diffs=diffs,
            graph_summary=graph_summary,
            narrative_summary=narrative_summary,
        )
        self.policy_service.repository.save_request_history(
            kind="changes",
            title="Policy change watch",
            status=self._summarize_status([old_record.status, new_record.status]),
            request_payload=payload.model_dump(),
            response_payload=response.model_dump(),
            summary=narrative_summary,
        )
        return response

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
        if record.step_therapy != "unknown":
            score += 4
        if record.site_of_care != "unknown":
            score += 4
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

    def _display_value(self, record, field: str, fallback: str) -> str:
        value = getattr(record, field)
        if self._is_unknown(value):
            derived = self._derive_from_evidence(record, field)
            if derived:
                return derived
            return fallback
        return value

    def _derive_from_evidence(self, record, field: str) -> str:
        joined = "\n".join(item.snippet for item in record.evidence if item.snippet)
        normalized = " ".join(joined.split())
        lowered = normalized.lower()
        if field == "effective_date":
            patterns = [
                r"Effective Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                r"Effective Date:\s*(\d{1,2}/\d{1,2}/\d{4})",
                r"effective\s+(\d{1,2}/\d{1,2}/\d{4})",
                r"Effective\s+(\d{1,2}/\d{1,2}/\d{4})",
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match:
                    return match.group(1).strip()
        if field == "step_therapy":
            patterns = [
                r"(try at least one Preferred Product.*?)(?:\.|;|$)",
                r"(must have .*? response to .*?)(?:\.|;|$)",
                r"(history of failure to .*?)(?:\.|;|$)",
                r"(trial of at least .*?)(?:\.|;|$)",
                r"(step[- ]therapy.*?)(?:\.|;|$)",
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match:
                    return match.group(1)[:260].strip()
        if field == "site_of_care":
            patterns = [
                r"(Site[- ]of[- ]Care.*?)(?:\.|;|$)",
                r"(medical benefit.*?)(?:\.|;|$)",
                r"(pharmacy benefit.*?)(?:\.|;|$)",
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match:
                    return match.group(1)[:300].strip()
        if field == "coverage_status":
            if "not covered" in lowered or "not medically necessary" in lowered:
                return "not covered"
            if "covered" in lowered or "medically necessary" in lowered or "precertification required" in lowered:
                return "covered with criteria"
        if field == "prior_auth_required":
            if "precertification" in lowered or "prior authorization" in lowered or "prior auth" in lowered:
                return "yes"
        return ""

    def _is_unknown(self, value) -> bool:
        lowered = str(value).strip().lower()
        return lowered in {"", "unknown", "none"}

    def _summarize_status(self, statuses: list[str]) -> str:
        lowered = [str(status).strip().lower() for status in statuses if str(status).strip()]
        if not lowered:
            return "unknown"
        if any(status == "answered" for status in lowered):
            return "answered"
        if any(status == "review required" for status in lowered):
            return "review required"
        if any(status == "partial" for status in lowered):
            return "partial"
        return lowered[0]
