import re

from ..models.schemas import AskRequest, AskResponse, DocumentSummary, PolicyRecord
from ..storage.repository import Repository
from .document_service import DocumentService
from .graph_service import GraphService
from .openai_service import OpenAIService
from .pageindex_service import PageIndexService


class PolicyService:
    VERSION_COMPARE_HINT = (
        "Summarize only the active coverage rules for this exact document version. "
        "Ignore policy history, review history, references, appendices, and background unless they are the only source of active criteria."
    )

    def __init__(
        self,
        document_service: DocumentService,
        pageindex_service: PageIndexService,
        graph_service: GraphService,
    ) -> None:
        self.document_service = document_service
        self.pageindex_service = pageindex_service
        self.graph_service = graph_service
        self.openai_service = OpenAIService()
        self.repository = Repository()

    def answer_question(self, payload: AskRequest, *, record_history: bool = True) -> AskResponse:
        documents = self.document_service.refresh_documents()
        if payload.payer_filters:
            selected = [doc for doc in documents if doc.payer in payload.payer_filters]
        else:
            selected = documents
        candidate_docs = self._select_best_documents(selected, payload.drug_name)

        records: list[PolicyRecord] = []
        for document in candidate_docs:
            record = self.answer_for_document(document, payload.drug_name, payload.question, top_k=payload.top_k)
            records.append(record)
        response = AskResponse(records=records)
        if record_history:
            self.repository.save_request_history(
                kind="ask",
                title=self._history_title(payload.question, "Prior auth check"),
                status=self._summarize_status([record.status for record in records]),
                request_payload=payload.model_dump(),
                response_payload=response.model_dump(),
                summary=self._summarize_ask_response(response),
            )
        return response

    def answer_for_document(
        self,
        document: DocumentSummary,
        drug_name: str,
        question: str,
        *,
        top_k: int = 4,
        retrieval_mode: str = "default",
    ) -> PolicyRecord:
        snippets = self._retrieve_policy_snippets(document, drug_name, question, top_k, retrieval_mode=retrieval_mode)
        cached = self.repository.get_cached_extraction(document.doc_id, drug_name, question, snippets)
        if cached:
            record = cached
        else:
            record = self.openai_service.extract_policy(document, drug_name, question, snippets)
            self.repository.save_cached_extraction(record, drug_name, question, snippets)
        self._refine_record_from_snippets(record, document, snippets)
        self.repository.save_cached_extraction(record, drug_name, question, snippets)
        record.graph_context = self.graph_service.persist_policy_record(record)
        self.repository.save_extraction(record, question)
        return record

    def save_compare_history(self, payload, response) -> None:
        self.repository.save_request_history(
            kind="compare",
            title="Coverage comparison",
            status=self._summarize_status([row.status for row in response.records]),
            request_payload=payload.model_dump(),
            response_payload=response.model_dump(),
            summary=f"Compared {len(response.rows)} payer rows for {payload.drug_name}.",
        )

    def save_change_history(self, payload, response) -> None:
        self.repository.save_request_history(
            kind="changes",
            title="Policy change watch",
            status=self._summarize_status([response.new_record.status, response.old_record.status]),
            request_payload=payload.model_dump(),
            response_payload=response.model_dump(),
            summary=response.narrative_summary,
        )

    def _retrieve_policy_snippets(
        self,
        document: DocumentSummary,
        drug_name: str,
        question: str,
        top_k: int,
        *,
        retrieval_mode: str = "default",
    ):
        queries = self._build_retrieval_queries(drug_name, question, document, retrieval_mode=retrieval_mode)
        seen = set()
        merged = []
        for query in queries:
            pageindex_snippets = self.pageindex_service.retrieve_snippets(document, query, top_k)
            fallback_snippets = self.document_service.retrieve_snippets(document, query, top_k)
            for snippet in [*pageindex_snippets, *fallback_snippets]:
                key = (snippet.page, snippet.section, snippet.snippet[:200])
                if key in seen:
                    continue
                seen.add(key)
                merged.append(snippet)
        filtered = self._filter_snippets(document, merged, retrieval_mode=retrieval_mode)
        return filtered[: max(top_k, 4)]

    def _build_retrieval_queries(
        self,
        drug_name: str,
        question: str,
        document: DocumentSummary,
        *,
        retrieval_mode: str = "default",
    ) -> list[str]:
        queries = [
            f"{drug_name} {question}",
            f"{drug_name} coverage rationale",
            f"{drug_name} prior authorization criteria",
            f"{drug_name} criteria for initial approval",
            f"{drug_name} medically necessary",
        ]
        if document.payer == "UnitedHealthcare":
            queries.extend(
                [
                    f"{drug_name} coverage rationale authorization",
                    f"{drug_name} diagnosis-specific medical necessity criteria",
                    f"{drug_name} applicable codes authorization",
                ]
            )
        if document.payer == "Aetna":
            queries.extend(
                [
                    f"{drug_name} requires precertification",
                    f"{drug_name} criteria for initial approval precertification",
                    f"{drug_name} site of care utilization management",
                ]
            )
        if retrieval_mode == "version_compare":
            queries.extend(
                [
                    f"{drug_name} active coverage rationale",
                    f"{drug_name} policy statement current criteria",
                    f"{drug_name} current authorization requirements",
                    f"{drug_name} {self.VERSION_COMPARE_HINT}",
                ]
            )
        return queries

    def _filter_snippets(
        self,
        document: DocumentSummary,
        snippets,
        *,
        retrieval_mode: str = "default",
    ):
        if retrieval_mode != "version_compare":
            return snippets

        low_value_markers = [
            "policy history",
            "review history",
            "references",
            "appendix",
            "background",
            "clinical evidence",
        ]
        filtered = [
            snippet
            for snippet in snippets
            if not any(marker in snippet.section.lower() for marker in low_value_markers)
        ]
        return filtered if len(filtered) >= 3 else snippets

    def _select_best_documents(self, documents: list[DocumentSummary], drug_name: str) -> list[DocumentSummary]:
        lowered = drug_name.lower()
        eligible = []
        for doc in documents:
            likely = (doc.likely_drug or "").lower()
            if doc.document_pattern == "single_drug" and likely and lowered not in likely and likely not in lowered:
                continue
            eligible.append(doc)
        if not eligible:
            eligible = documents

        def score(doc: DocumentSummary) -> tuple[int, int, int, str]:
            policy_name = doc.policy_name.lower()
            likely = (doc.likely_drug or "").lower()
            exact_name = 1 if lowered in policy_name else 0
            likely_match = 1 if lowered in likely else 0
            single_drug = 1 if doc.document_pattern == "single_drug" else 0
            return (exact_name, likely_match, single_drug, doc.policy_name)

        best_by_payer: dict[str, DocumentSummary] = {}
        for doc in eligible:
            current = best_by_payer.get(doc.payer)
            if current is None or score(doc) > score(current):
                best_by_payer[doc.payer] = doc
        return list(best_by_payer.values())

    def _refine_record_from_snippets(
        self,
        record: PolicyRecord,
        document: DocumentSummary,
        snippets,
    ) -> None:
        joined = "\n".join(snippet.snippet for snippet in snippets if snippet.snippet)
        if record.effective_date == "unknown":
            effective_date = self._extract_effective_date(joined)
            if effective_date == "unknown" and document.version_label != "current":
                effective_date = document.version_label
            if effective_date != "unknown":
                record.effective_date = effective_date

        if record.prior_auth_required == "unknown":
            prior_auth = self._extract_prior_auth_required(joined)
            if prior_auth != "unknown":
                record.prior_auth_required = prior_auth

        if record.step_therapy == "unknown":
            step_therapy = self._extract_step_therapy(joined)
            if step_therapy != "unknown":
                record.step_therapy = step_therapy

        if record.site_of_care == "unknown":
            site_of_care = self._extract_site_of_care(joined)
            if site_of_care != "unknown":
                record.site_of_care = site_of_care

        if record.dosing_quantity_limits == "unknown":
            dosing_limits = self._extract_dosing_limits(joined)
            if dosing_limits != "unknown":
                record.dosing_quantity_limits = dosing_limits

        if record.coverage_status == "unknown":
            coverage = self._extract_coverage_status(joined)
            if coverage != "unknown":
                record.coverage_status = coverage

    def _extract_effective_date(self, text: str) -> str:
        patterns = [
            r"Effective Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            r"Effective Date:\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"effective\s+(\d{1,2}/\d{1,2}/\d{4})",
            r"Effective\s+(\d{1,2}/\d{1,2}/\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return "unknown"

    def _extract_prior_auth_required(self, text: str) -> str:
        lowered = text.lower()
        if "precertification" in lowered or "prior authorization" in lowered or "prior auth" in lowered:
            return "yes"
        return "unknown"

    def _extract_step_therapy(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text)
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
        return "unknown"

    def _extract_site_of_care(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text)
        patterns = [
            r"(Site[- ]of[- ]Care.*?)(?:\.|;|$)",
            r"(medical benefit.*?)(?:\.|;|$)",
            r"(pharmacy benefit.*?)(?:\.|;|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return match.group(1)[:300].strip()
        return "unknown"

    def _extract_dosing_limits(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text)
        patterns = [
            r"(limited to(?: no more than)? \d+ doses)(?:\.|;|$)",
            r"(authorization limited to(?: no more than)? \d+ doses)(?:\.|;|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return "unknown"

    def _extract_coverage_status(self, text: str) -> str:
        lowered = text.lower()
        if "not covered" in lowered or "not medically necessary" in lowered:
            return "not covered"
        if "covered" in lowered or "medically necessary" in lowered or "precertification required" in lowered:
            return "covered with criteria"
        return "unknown"

    def _summarize_ask_response(self, response: AskResponse) -> str:
        if not response.records:
            return "No policy records were found."
        answered = [record for record in response.records if record.status == "Answered"]
        partial = [record for record in response.records if record.status != "Answered"]
        if answered:
            return f"Answered {len(answered)} payer policy question(s) with evidence-backed records."
        if partial:
            return f"Returned {len(partial)} partial policy record(s) with evidence-backed fallback output."
        return "No policy records were found."

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

    def _history_title(self, question: str, fallback: str) -> str:
        cleaned = " ".join(str(question).split()).strip()
        if not cleaned:
            return fallback
        return cleaned[:96]
