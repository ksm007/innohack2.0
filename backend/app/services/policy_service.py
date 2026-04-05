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

    def answer_question(self, payload: AskRequest) -> AskResponse:
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
        return AskResponse(records=records)

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
        record.graph_context = self.graph_service.persist_policy_record(record)
        self.repository.save_extraction(record, question)
        return record

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
