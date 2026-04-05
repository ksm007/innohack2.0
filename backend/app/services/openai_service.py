import ast
import json
import re
from pathlib import Path

from openai import OpenAI

from ..core.config import settings
from ..models.schemas import DiffEntry, DocumentSummary, EvidenceSnippet, PolicyRecord


class OpenAIService:
    def __init__(self) -> None:
        self._client = None
        if settings.openai_api_key:
            self._client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)

    def extract_policy(
        self,
        document: DocumentSummary,
        drug_name: str,
        question: str,
        snippets: list[EvidenceSnippet],
    ) -> PolicyRecord:
        if not snippets:
            return self._fallback_record(document, drug_name, [], status="No policy found", answer="No matching policy evidence was found in the local document set.")

        if not self._client:
            return self._fallback_record(
                document,
                drug_name,
                snippets,
                status="Partial",
                answer="OpenAI is not configured yet. Returning evidence-only fallback output.",
            )

        prompt_text = self._load_prompt()
        evidence_payload = [snippet.model_dump() for snippet in snippets]
        user_prompt = (
            f"Drug name: {drug_name}\n"
            f"Question: {question}\n"
            f"Payer: {document.payer}\n"
            f"Policy: {document.policy_name}\n"
            f"Document pattern: {document.document_pattern}\n"
            f"Evidence snippets:\n{json.dumps(evidence_payload, indent=2)}"
        )
        try:
            response = self._client.chat.completions.create(
                model=settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_content = response.choices[0].message.content or "{}"
            payload = self._normalize_llm_payload(json.loads(raw_content), document, drug_name)
            payload["doc_id"] = document.doc_id
            payload["payer"] = document.payer
            payload["policy_name"] = document.policy_name
            payload["answer"] = self._build_answer(payload, question)
            payload["source_method"] = "openai_plus_retrieval"
            payload["evidence"] = evidence_payload
            return PolicyRecord.model_validate(payload)
        except Exception:
            return self._fallback_record(
                document,
                drug_name,
                snippets,
                status="Partial",
                answer="OpenAI is configured but unavailable from the current environment. Returning evidence-only fallback output.",
            )

    def summarize_diff(self, old_record: PolicyRecord, new_record: PolicyRecord, diffs: list[DiffEntry]) -> str:
        if not diffs:
            return "No structured field changes were detected between the selected policy versions."
        if not self._client:
            return self._fallback_diff_summary(diffs)

        prompt_path = Path(settings.prompts_dir) / "summarize_diff.txt"
        prompt_text = prompt_path.read_text(encoding="utf-8")
        user_prompt = json.dumps(
            {
                "old_record": old_record.model_dump(),
                "new_record": new_record.model_dump(),
                "diffs": [diff.model_dump() for diff in diffs],
            },
            indent=2,
        )
        try:
            response = self._client.chat.completions.create(
                model=settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": user_prompt},
                ],
            )
            payload = json.loads(response.choices[0].message.content or "{}")
            summary = self._as_string(payload.get("summary"))
            meaningful = self._as_list(payload.get("meaningful_changes"))
            cosmetic = self._as_list(payload.get("cosmetic_or_uncertain_changes"))
            parts = [summary]
            if meaningful:
                parts.append(f"Meaningful: {'; '.join(meaningful[:3])}.")
            if cosmetic:
                parts.append(f"Cosmetic/uncertain: {'; '.join(cosmetic[:3])}.")
            return " ".join(part for part in parts if part and part != "unknown")
        except Exception:
            return self._fallback_diff_summary(diffs)

    def _fallback_record(
        self,
        document: DocumentSummary,
        drug_name: str,
        snippets: list[EvidenceSnippet],
        status: str,
        answer: str,
    ) -> PolicyRecord:
        heuristic_payload = self._heuristic_extract(document, drug_name, snippets)
        heuristic_payload.update(
            {
                "doc_id": document.doc_id,
                "payer": document.payer,
                "policy_name": document.policy_name,
                "document_pattern": document.document_pattern,
                "drug_name_brand": drug_name,
                "status": heuristic_payload.get("status", status),
                "answer": heuristic_payload.get("answer", answer),
                "confidence": heuristic_payload.get("confidence", "low" if snippets else "none"),
                "evidence": snippets,
                "source_method": "heuristic_fallback",
            }
        )
        return PolicyRecord(
            **heuristic_payload,
        )

    def _build_answer(self, payload: dict, question: str) -> str:
        coverage = payload.get("coverage_status", "unknown")
        pa = payload.get("prior_auth_required", "unknown")
        step_therapy = payload.get("step_therapy", "unknown")
        return (
            f"{payload.get('payer', 'This payer')} coverage summary for '{question}': "
            f"coverage={coverage}, prior_auth={pa}, step_therapy={step_therapy}."
        )

    def _load_prompt(self) -> str:
        prompt_path = Path(settings.prompts_dir) / "extract_policy_fields.txt"
        return prompt_path.read_text(encoding="utf-8")

    def _normalize_llm_payload(self, payload: dict, document: DocumentSummary, drug_name: str) -> dict:
        normalized = dict(payload)
        normalized["payer"] = document.payer
        normalized["policy_name"] = document.policy_name
        normalized["document_pattern"] = normalized.get("document_pattern") or document.document_pattern
        normalized["effective_date"] = self._as_string(normalized.get("effective_date"))
        normalized["drug_name_brand"] = self._normalize_brand_name(normalized.get("drug_name_brand"), drug_name)
        normalized["drug_name_generic"] = self._as_string(normalized.get("drug_name_generic"))
        normalized["drug_category"] = self._as_string(normalized.get("drug_category"))
        normalized["access_status"] = self._as_string(normalized.get("access_status"))
        normalized["preferred_status_rank"] = self._as_string(normalized.get("preferred_status_rank"))
        normalized["covered_indications"] = self._as_list(normalized.get("covered_indications"))
        normalized["coverage_status"] = self._normalize_coverage_status(normalized.get("coverage_status"))
        normalized["prior_auth_required"] = self._normalize_yes_no(normalized.get("prior_auth_required"))
        normalized["prior_auth_criteria"] = self._as_string(normalized.get("prior_auth_criteria"))
        normalized["step_therapy"] = self._as_string(normalized.get("step_therapy"))
        normalized["site_of_care"] = self._as_string(normalized.get("site_of_care"))
        normalized["dosing_quantity_limits"] = self._as_string(normalized.get("dosing_quantity_limits"))
        normalized["hcpcs_codes"] = self._as_list(normalized.get("hcpcs_codes"))
        normalized["biosimilar_reference_relationships"] = self._normalize_biosimilars(
            normalized.get("biosimilar_reference_relationships")
        )
        normalized["confidence"] = self._normalize_confidence(normalized.get("confidence"))
        normalized["status"] = self._normalize_status(normalized.get("status"))
        return normalized

    def _heuristic_extract(
        self,
        document: DocumentSummary,
        drug_name: str,
        snippets: list[EvidenceSnippet],
    ) -> dict:
        joined = "\n".join(snippet.snippet for snippet in snippets)
        lowered = joined.lower()
        effective_date = self._find_effective_date(joined)
        hcpcs_codes = sorted(set(re.findall(r"\b[AJQ]\d{4}\b", joined)))
        biosimilars = self._find_biosimilars(joined, drug_name)
        covered_indications = self._find_indications(joined)
        coverage_status = self._find_coverage_status(lowered)
        prior_auth_required = self._find_prior_auth_required(lowered)
        prior_auth_criteria = self._find_prior_auth_criteria(joined)
        step_therapy = self._find_step_therapy(joined)
        site_of_care = self._find_site_of_care(joined)
        drug_generic = self._find_generic_name(joined, drug_name)
        access_status, preferred_rank = self._find_access_status(lowered)
        dosing_limits = self._find_dosing(joined)
        confidence = "medium" if any(
            value not in ("unknown", [], None)
            for value in [effective_date, hcpcs_codes, covered_indications, coverage_status, prior_auth_required]
        ) else "low"
        status = self._determine_status(snippets, coverage_status, prior_auth_required, covered_indications)
        answer = (
            f"{document.payer} coverage summary: coverage={coverage_status}, prior_auth={prior_auth_required}, "
            f"step_therapy={step_therapy}, indications={', '.join(covered_indications[:3]) or 'unknown'}."
        )
        return {
            "effective_date": effective_date,
            "drug_name_generic": drug_generic,
            "drug_category": self._find_category(joined),
            "access_status": access_status,
            "preferred_status_rank": preferred_rank,
            "covered_indications": covered_indications,
            "coverage_status": coverage_status,
            "prior_auth_required": prior_auth_required,
            "prior_auth_criteria": prior_auth_criteria,
            "step_therapy": step_therapy,
            "site_of_care": site_of_care,
            "dosing_quantity_limits": dosing_limits,
            "hcpcs_codes": hcpcs_codes,
            "biosimilar_reference_relationships": biosimilars,
            "confidence": confidence,
            "status": status,
            "answer": answer,
        }

    def _find_effective_date(self, text: str) -> str:
        patterns = [
            r"Effective Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            r"Effective\s+(\d{2}/\d{2}/\d{4})",
            r"Effective Date:\s*(\d{2}/\d{2}/\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return "unknown"

    def _find_coverage_status(self, lowered: str) -> str:
        if "not covered" in lowered:
            return "not covered"
        if "experimental, investigational, or unproven" in lowered:
            return "not covered"
        if "medically necessary" in lowered or "is proven for the treatment" in lowered or "coverage for" in lowered:
            return "covered with criteria"
        return "unknown"

    def _find_prior_auth_required(self, lowered: str) -> str:
        if "precertification" in lowered or "prior authorization" in lowered or "prior auth" in lowered:
            return "yes"
        return "unknown"

    def _find_prior_auth_criteria(self, text: str) -> str:
        patterns = [
            r"(Criteria for Initial Approval.*?)(?:III\.|Continuation of therapy|Applicable CPT|Applicable Codes|$)",
            r"(General Requirements.*?)(?:Diagnosis-Specific Requirements|$)",
            r"(Preferred Product Criteria.*?)(?:Diagnosis-Specific Criteria|$)",
        ]
        normalized = re.sub(r"\s+", " ", text)
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return match.group(1)[:800].strip()
        return "unknown"

    def _find_step_therapy(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text)
        patterns = [
            r"(History of failure to .*?)(?: or\s+Patient| Patient| Prescribed| Refer to| For continuation| Additional information|$)",
            r"(must try .*?)(?:\.|;|$)",
            r"(trial of at least .*?)(?:\.|;|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return match.group(1)[:260].strip(" .;")
        if "step therapy" in normalized.lower():
            return "refer to step therapy criteria in evidence"
        return "unknown"

    def _find_site_of_care(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text)
        match = re.search(r"(Site of Care.*?)(?:\.|;|$)", normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1)[:300].strip()
        return "unknown"

    def _find_dosing(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text)
        match = re.search(r"(dosed according to .*?)(?:\.|;|$)", normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1)[:300].strip()
        return "unknown"

    def _find_category(self, text: str) -> str:
        lowered = text.lower()
        category_map = {
            "oncology": "oncology",
            "immunology": "immunology",
            "inflammatory": "inflammatory conditions",
            "botulinum toxin": "neurology",
            "biosimilar": "biologic",
        }
        for token, category in category_map.items():
            if token in lowered:
                return category
        return "unknown"

    def _find_access_status(self, lowered: str) -> tuple[str, str]:
        if "non-preferred" in lowered:
            return "non-preferred", "unknown"
        if "preferred product criteria" in lowered or "preferred" in lowered:
            return "preferred", "unknown"
        return "unknown", "unknown"

    def _find_generic_name(self, text: str, drug_name: str) -> str:
        patterns = [
            rf"{re.escape(drug_name)}\s*\(([^)]+)\)",
            r"\b([a-z]+(?:-[a-z]+)?)\s*\((?:Remicade|Inflectra|Avsola|Renflexis|Botox|Xeomin|Dysport)[^)]+\)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if len(candidate) > 2:
                    return candidate
        return "unknown"

    def _find_indications(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text)
        patterns = [
            r"treatment of ([A-Za-z0-9 ,'\-()/]+?)(?: when| and |\.|;)",
            r"is proven for the treatment of ([A-Za-z0-9 ,'\-()/]+?)(?: when| and |\.|;)",
            r"following conditions:(.*?)(?:Additional information|Page \d+ of|$)",
        ]
        findings: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
                value = match.group(1).strip(" -")
                if "following conditions" in value.lower():
                    continue
                if len(value) > 3 and len(value) < 120:
                    findings.append(value)
        cleaned = []
        for item in findings:
            item = re.sub(r"^\W+|\W+$", "", item)
            if item and item.lower() not in {value.lower() for value in cleaned}:
                cleaned.append(item)
        return cleaned[:10]

    def _find_biosimilars(self, text: str, drug_name: str) -> list[str]:
        brand_candidates = re.findall(r"\b([A-Z][A-Za-z0-9-]+)®", text)
        results = []
        for candidate in brand_candidates:
            if candidate.lower() != drug_name.lower():
                results.append(candidate)
        if "biosimilar" in text.lower():
            for token in ["Avsola", "Inflectra", "Renflexis", "Zymfentra"]:
                if token.lower() in text.lower() and token not in results:
                    results.append(token)
        return sorted(set(results))

    def _determine_status(
        self,
        snippets: list[EvidenceSnippet],
        coverage_status: str,
        prior_auth_required: str,
        covered_indications: list[str],
    ) -> str:
        if not snippets:
            return "No policy found"
        if coverage_status == "not covered":
            return "Not covered"
        if coverage_status != "unknown" and (prior_auth_required != "unknown" or covered_indications):
            return "Answered"
        return "Partial"

    def _as_string(self, value) -> str:
        if value in (None, "", [], {}):
            return "unknown"
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, list):
            parts = [self._clean_text(str(item)) for item in value if item not in (None, "")]
            parts = [part for part in parts if part and part != "unknown"]
            return ", ".join(parts) if parts else "unknown"
        if isinstance(value, dict):
            fragments = self._extract_structured_text_fragments(value)
            return ", ".join(fragments) if fragments else "unknown"
        return self._clean_text(str(value))

    def _as_list(self, value) -> list[str]:
        if value in (None, "", "unknown"):
            return []
        if isinstance(value, list):
            return self._dedupe_preserve_order(
                [
                    item
                    for raw_item in value
                    for item in self._normalize_list_item(raw_item)
                ]
            )
        if isinstance(value, dict):
            return self._dedupe_preserve_order(self._extract_structured_text_fragments(value))
        return self._dedupe_preserve_order(self._normalize_list_item(value))

    def _normalize_brand_name(self, value, fallback: str) -> str:
        if isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            return joined or fallback
        string_value = self._as_string(value)
        return fallback if string_value == "unknown" else string_value

    def _normalize_yes_no(self, value) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        lowered = self._as_string(value).lower()
        if lowered in {"yes", "true", "required"} or lowered.startswith("yes"):
            return "yes"
        if lowered in {"no", "false", "not required"} or lowered.startswith("no"):
            return "no"
        return "unknown" if lowered == "unknown" else lowered

    def _normalize_biosimilars(self, value) -> list[str]:
        candidates = self._as_list(value)
        normalized = []
        for item in candidates:
            normalized.extend(self._extract_biosimilar_names(item))
        return self._dedupe_preserve_order(normalized)

    def _normalize_status(self, value) -> str:
        lowered = self._as_string(value).lower()
        if lowered in {"answered", "coverage policy found", "policy found", "covered"}:
            return "Answered"
        if lowered == "partial":
            return "Partial"
        if lowered == "review required":
            return "Review required"
        if lowered == "no policy found":
            return "No policy found"
        if lowered == "not covered":
            return "Not covered"
        return "Answered" if lowered != "unknown" else "Partial"

    def _normalize_confidence(self, value) -> str:
        lowered = self._as_string(value).lower()
        if lowered in {"high", "medium", "low"}:
            return lowered
        return "medium" if lowered != "unknown" else "low"

    def _normalize_coverage_status(self, value) -> str:
        lowered = self._as_string(value).lower()
        if lowered in {"unknown", ""}:
            return "unknown"
        if "not covered" in lowered or "not medically necessary" in lowered:
            return "not covered"
        if "covered" in lowered or "criteria" in lowered or "medically necessary" in lowered:
            return "covered with criteria"
        return lowered

    def _fallback_diff_summary(self, diffs: list[DiffEntry]) -> str:
        meaningful = [diff.field for diff in diffs if diff.change_type == "meaningful"]
        cosmetic = [diff.field for diff in diffs if diff.change_type != "meaningful"]
        if not meaningful:
            return "No clearly meaningful coverage or utilization-management changes were detected in the selected fields."
        summary = f"Meaningful changes detected in: {', '.join(meaningful[:5])}."
        if cosmetic:
            summary += f" Additional cosmetic/admin changes: {', '.join(cosmetic[:3])}."
        return summary

    def _normalize_list_item(self, value) -> list[str]:
        if value in (None, "", "unknown"):
            return []
        if isinstance(value, dict):
            return self._extract_structured_text_fragments(value)
        if isinstance(value, list):
            items: list[str] = []
            for child in value:
                items.extend(self._normalize_list_item(child))
            return items
        text = self._clean_text(str(value))
        if not text or text == "unknown":
            return []
        return [text]

    def _extract_structured_text_fragments(self, value: dict) -> list[str]:
        preferred_keys = ["brand_name", "product", "reference", "relationship", "route", "value", "name"]
        fragments = []
        for key in preferred_keys:
            raw = value.get(key)
            cleaned = self._clean_text(str(raw)) if raw not in (None, "") else ""
            if cleaned and cleaned != "unknown":
                fragments.append(cleaned)
        if fragments:
            return self._dedupe_preserve_order(fragments)
        fallback = []
        for raw in value.values():
            cleaned = self._clean_text(str(raw)) if raw not in (None, "") else ""
            if cleaned and cleaned != "unknown":
                fallback.append(cleaned)
        return self._dedupe_preserve_order(fallback)

    def _extract_biosimilar_names(self, value: str) -> list[str]:
        text = self._clean_text(value)
        parsed = self._try_parse_mapping_string(text)
        if parsed:
            text = ", ".join(self._extract_structured_text_fragments(parsed))

        matches = re.findall(r"\b[A-Z][A-Za-z0-9-]+(?:\s+[A-Z][A-Za-z0-9-]+)*\b", text)
        filtered = []
        ignored = {"Policy", "No", "Other", "Preferred", "Non", "Biosimilars", "Product", "Products"}
        for match in matches:
            candidate = self._clean_text(match)
            if candidate in ignored or len(candidate) < 3:
                continue
            filtered.append(candidate)
        if filtered:
            return self._dedupe_preserve_order(filtered)
        return [text] if text and text != "unknown" else []

    def _try_parse_mapping_string(self, value: str) -> dict | None:
        if not value.startswith("{") or not value.endswith("}"):
            return None
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _clean_text(self, value: str) -> str:
        cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", value)
        cleaned = cleaned.replace("\u2011", "-").replace("\u2012", "-").replace("\u2013", "-").replace("\u2014", "-")
        cleaned = cleaned.replace("\u00ae", "").replace("\u2122", "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:-")
        return cleaned or "unknown"

    def _dedupe_preserve_order(self, values: list[str]) -> list[str]:
        seen = set()
        results = []
        for value in values:
            cleaned = self._clean_text(value)
            key = cleaned.lower()
            if cleaned == "unknown" or key in seen:
                continue
            seen.add(key)
            results.append(cleaned)
        return results
