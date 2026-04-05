import hashlib
import re
import subprocess
from pathlib import Path

from pypdf import PdfReader

from ..core.config import settings
from ..models.schemas import DocumentSummary, EvidenceSnippet
from ..storage.repository import Repository


class DocumentService:
    _checksum_cache: dict[Path, tuple[int, int, str]] = {}

    CANONICAL_DRUG_ALIASES = {
        "infliximab": ["infliximab", "remicade", "inflectra", "avsola", "renflexis"],
        "ustekinumab": ["ustekinumab", "stelara", "wezlana", "yesintek", "steqeyma", "imuldosa", "otulfi", "pyzchiva", "selarsdi"],
        "rituximab": ["rituximab", "rituxan", "truxima", "ruxience", "riabni"],
        "denosumab": ["denosumab", "prolia", "xgeva", "jubbonti", "wyost", "ospomyv", "enoby", "conexxence", "bildyos", "bosaya", "stoboclo"],
        "bevacizumab": ["bevacizumab", "bevecizumab", "avastin", "mvasi", "zirabev", "alymsys", "vegzelma", "jobevne", "avzivi"],
        "botulinum_toxins": ["botulinum", "botox", "dysport", "xeomin", "myobloc", "jeuveau"],
    }

    def __init__(self) -> None:
        self.repository = Repository()

    def refresh_documents(self) -> list[DocumentSummary]:
        documents: list[DocumentSummary] = []
        seen_checksums: dict[str, Path] = {}
        pdf_paths = sorted(settings.docs_dir.glob("*.pdf"), key=self._document_sort_key)
        for path in pdf_paths:
            checksum = self._file_checksum(path)
            if checksum in seen_checksums:
                continue
            seen_checksums[checksum] = path
            documents.append(self._build_summary(path))
        self.repository.upsert_documents(documents)
        return documents

    def get_document(self, doc_id: str) -> DocumentSummary:
        for document in self.refresh_documents():
            if document.doc_id == doc_id:
                return document
        raise ValueError(f"Document not found: {doc_id}")

    def extract_text(self, path: Path) -> str:
        cache_path = settings.cache_dir / f"{path.stem}.txt"
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        text = self._extract_with_pdftotext(path) or self._extract_with_pypdf(path)
        cache_path.write_text(text, encoding="utf-8")
        return text

    def retrieve_snippets(self, document: DocumentSummary, query: str, top_k: int = 3) -> list[EvidenceSnippet]:
        text = self.extract_text(Path(document.path))
        pages = [page.strip() for page in text.split("\f")]
        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9-]+", query) if len(term) > 2]
        query_lower = query.lower()
        scored_pages: list[tuple[int, int, str]] = []
        for page_number, page_text in enumerate(pages, start=1):
            lowered = page_text.lower()
            score = self._score_page(document, lowered, query_lower, terms, page_number)
            if score:
                scored_pages.append((score, page_number, page_text))
        scored_pages.sort(key=lambda item: (item[0], -item[1]), reverse=True)

        results = []
        for score, page_number, page_text in scored_pages[:top_k]:
            snippet = self._trim_snippet(page_text, terms)
            results.append(
                EvidenceSnippet(
                    page=page_number,
                    section=self._infer_section(snippet),
                    snippet=snippet,
                    retrieval_method="keyword_fallback",
                )
            )
        return results

    def _score_page(self, document: DocumentSummary, lowered: str, query_lower: str, terms: list[str], page_number: int) -> int:
        score = sum(lowered.count(term) for term in terms)
        likely_drug = (document.likely_drug or "").lower()
        if likely_drug:
            score += lowered.count(likely_drug) * 6
        if query_lower and query_lower in lowered:
            score += 12

        high_value_phrases = [
            "coverage rationale",
            "diagnosis-specific criteria",
            "criteria for initial approval",
            "general requirements",
            "precertification",
            "prior authorization",
            "medically necessary",
            "applicable codes",
            "site of care",
            "policy history",
            "effective date",
            "proven for the treatment",
            "is proven for the treatment",
        ]
        for phrase in high_value_phrases:
            if phrase in lowered:
                score += 8

        if "hcpcs" in lowered or re.search(r"\b[AJQ]\d{4}\b", lowered):
            score += 5

        if document.document_pattern == "multi_drug":
            if page_number <= 20:
                score += 8
            if "medical clinical policy bulletins" in lowered:
                score += 4

        low_value_phrases = [
            "clinical evidence",
            "references",
            "study",
            "patients",
            "meta-analysis",
            "follow-up",
            "authors concluded",
        ]
        for phrase in low_value_phrases:
            if phrase in lowered:
                score -= 4

        return max(score, 0)

    def _build_summary(self, path: Path) -> DocumentSummary:
        stem = path.stem
        normalized_stem = stem.lower()
        normalized_phrase_stem = re.sub(r"[\W_]+", " ", normalized_stem).strip()
        payer = self._infer_payer(normalized_stem)
        if payer == "Unknown":
            payer = self._infer_payer_from_content(path)
        version_label = self._infer_version_label(normalized_stem)
        document_pattern = self._infer_pattern(normalized_phrase_stem)
        likely_drug = self._infer_drug_name(stem)
        policy_name = stem.replace("_", " ")
        return DocumentSummary(
            doc_id=normalized_stem.replace(" ", "_"),
            payer=payer,
            policy_name=policy_name,
            path=str(path.resolve()),
            version_label=version_label,
            document_pattern=document_pattern,
            likely_drug=likely_drug,
            version_group=self._infer_version_group(payer, policy_name, likely_drug, document_pattern),
        )

    def _extract_with_pdftotext(self, path: Path) -> str:
        try:
            result = subprocess.run(
                ["pdftotext", str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""

    def _extract_with_pypdf(self, path: Path) -> str:
        reader = PdfReader(str(path))
        return "\f".join(page.extract_text() or "" for page in reader.pages)

    def _document_sort_key(self, path: Path) -> tuple[int, str]:
        return (1 if re.search(r"\s\(\d+\)$", path.stem) else 0, path.name.lower())

    def _file_checksum(self, path: Path) -> str:
        stat = path.stat()
        cached = self._checksum_cache.get(path)
        cache_key = (stat.st_mtime_ns, stat.st_size)
        if cached and cached[:2] == cache_key:
            return cached[2]

        digest = hashlib.sha1()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum = digest.hexdigest()
        self._checksum_cache[path] = (*cache_key, checksum)
        return checksum

    def _infer_payer(self, stem: str) -> str:
        payer_map = {
            "uhc": "UnitedHealthcare",
            "unitedhealthcare": "UnitedHealthcare",
            "cigna": "Cigna",
            "priority health": "Priority Health",
            "florida blue": "Florida Blue",
            "bcbs": "BCBS NC",
            "emblemhealth": "EmblemHealth",
            "aetna": "Aetna",
            "provider-administered": "Priority Health",
        }
        for token, payer in payer_map.items():
            if token in stem:
                return payer
        return "Unknown"

    def _infer_payer_from_content(self, path: Path) -> str:
        text = self.extract_text(path)[:2000].lower()
        return self._infer_payer(text)

    def _infer_version_label(self, stem: str) -> str:
        match = re.search(r"(\d{8}|20\d{2})", stem)
        return match.group(1) if match else "current"

    def _infer_pattern(self, stem: str) -> str:
        single_drug_overrides = ["medical clinical policy bulletins", "medical benefit drug policy", "drug policy"]
        if any(token in stem for token in single_drug_overrides) and not any(
            token in stem for token in ["summary", "drug list", "preferred products", "policy updates", "provider-administered"]
        ):
            return "single_drug"
        multi_tokens = [
            "summary",
            "drug list",
            "preferred products",
            "policy updates",
            "provider administered",
            "update bulletin",
        ]
        return "multi_drug" if any(token in stem for token in multi_tokens) else "single_drug"

    def _infer_drug_name(self, stem: str) -> str | None:
        canonical = self._canonical_drug_key(stem)
        if canonical:
            return canonical.replace("_", " ").title()
        cleaned = re.sub(r"[\W_]+", " ", stem).strip()
        stop_words = {
            "medical",
            "clinical",
            "policy",
            "bulletins",
            "products",
            "commercial",
            "coverage",
            "criteria",
            "summary",
            "change",
            "changes",
            "provider",
            "administered",
            "preferred",
        }
        words = [word for word in cleaned.split() if word.lower() not in stop_words and not word.isdigit()]
        if not words:
            return None
        return " ".join(words[:4])

    def _infer_version_group(
        self,
        payer: str,
        policy_name: str,
        likely_drug: str | None,
        document_pattern: str,
    ) -> str | None:
        if document_pattern == "single_drug":
            normalized = re.sub(r"[^a-z0-9]+", "_", policy_name.lower()).strip("_")
            normalized = re.sub(r"_(20\d{2}|\d{8})$", "", normalized)
            normalized = re.sub(r"_v\d+$", "", normalized)
            if normalized:
                return f"{payer}::{normalized}"
        canonical = self._canonical_drug_key(f"{policy_name} {likely_drug or ''}")
        if canonical:
            return f"{payer}::{canonical}"
        return None

    def _canonical_drug_key(self, text: str) -> str | None:
        lowered = re.sub(r"[\W_]+", " ", text.lower()).strip()
        for canonical, aliases in self.CANONICAL_DRUG_ALIASES.items():
            if any(alias in lowered for alias in aliases):
                return canonical
        return None

    def _trim_snippet(self, page_text: str, terms: list[str]) -> str:
        condensed = re.sub(r"\s+", " ", page_text).strip()
        if len(condensed) <= 700:
            return condensed
        anchor_terms = [
            "coverage rationale",
            "criteria for initial approval",
            "diagnosis-specific criteria",
            "precertification",
            "prior authorization",
            "medically necessary",
            "site of care",
            "applicable codes",
            *terms,
        ]
        for term in anchor_terms:
            position = condensed.lower().find(term)
            if position != -1:
                start = max(0, position - 180)
                end = min(len(condensed), position + 520)
                return condensed[start:end].strip()
        return condensed[:700].strip()

    def _infer_section(self, snippet: str) -> str:
        markers = ["coverage", "authorization", "site of care", "step therapy", "indications"]
        lowered = snippet.lower()
        for marker in markers:
            if marker in lowered:
                return marker.title()
        return "Relevant excerpt"
