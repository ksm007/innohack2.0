import json
import subprocess
from pathlib import Path
from threading import Lock, Thread

from ..core.config import settings
from ..models.schemas import DocumentSummary, EvidenceSnippet, IndexBuildResult
from ..storage.repository import Repository


class PageIndexService:
    _build_lock = Lock()
    _warmup_lock = Lock()
    _warmup_thread: Thread | None = None
    _warmup_enabled = settings.pageindex_warmup_on_startup
    _warmup_stop_requested = False

    def __init__(self) -> None:
        self.repository = Repository()

    def build_index(self, document: DocumentSummary, force: bool = False) -> IndexBuildResult:
        index_dir = self._index_dir(document)
        index_dir.mkdir(parents=True, exist_ok=True)

        if not settings.pageindex_root_path:
            detail = "PAGEINDEX_ROOT is not configured. Using keyword fallback retrieval until a local PageIndex clone is available."
            self.repository.save_pageindex_run(document.doc_id, "skipped", str(index_dir), detail)
            return IndexBuildResult(doc_id=document.doc_id, status="skipped", detail=detail, index_dir=str(index_dir))

        if not force:
            cached_tree = self._find_tree_file(index_dir)
            if cached_tree:
                detail = f"Using cached PageIndex tree at {cached_tree.name}"
                self.repository.save_pageindex_run(document.doc_id, "cached", str(index_dir), detail)
                return IndexBuildResult(doc_id=document.doc_id, status="cached", detail=detail, index_dir=str(index_dir))

        runner = settings.pageindex_root_path / "run_pageindex.py"
        if not runner.exists():
            detail = f"run_pageindex.py not found under {settings.pageindex_root_path}"
            self.repository.save_pageindex_run(document.doc_id, "failed", str(index_dir), detail)
            return IndexBuildResult(doc_id=document.doc_id, status="failed", detail=detail, index_dir=str(index_dir))

        command = [
            settings.pageindex_python_path,
            str(runner),
            "--pdf_path",
            document.path,
        ]
        if settings.openai_model:
            command.extend(["--model", settings.openai_model])
        try:
            with self._build_lock:
                subprocess.run(
                    command,
                    cwd=index_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            detail = "PageIndex command completed. Inspect the index directory for generated tree artifacts."
            status = "completed"
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or "PageIndex execution failed."
            status = "failed"

        self.repository.save_pageindex_run(document.doc_id, status, str(index_dir), detail)
        return IndexBuildResult(doc_id=document.doc_id, status=status, detail=detail, index_dir=str(index_dir))

    def build_indexes(self, documents: list[DocumentSummary], force: bool = False) -> list[IndexBuildResult]:
        return [self.build_index(document, force=force) for document in documents]

    def has_index(self, document: DocumentSummary) -> bool:
        return self._find_tree_file(self._index_dir(document)) is not None

    def start_default_warmup(self, documents: list[DocumentSummary]) -> bool:
        if not documents or not settings.pageindex_root_path:
            return False
        return self._start_warmup_thread(documents)

    def get_warmup_status(self) -> tuple[bool, bool, str]:
        running = False
        with self._warmup_lock:
            running = self._warmup_thread is not None and self._warmup_thread.is_alive()
            enabled = self._warmup_enabled
        if not settings.pageindex_root_path:
            detail = "PAGEINDEX_ROOT is not configured."
        elif running:
            detail = "Background PageIndex warmup is running."
        elif enabled:
            detail = "Background PageIndex warmup is enabled."
        else:
            detail = "Background PageIndex warmup is disabled."
        return enabled, running, detail

    def set_warmup_enabled(self, enabled: bool, documents: list[DocumentSummary]) -> tuple[bool, bool, str]:
        with self._warmup_lock:
            self._warmup_enabled = enabled
            self._warmup_stop_requested = not enabled
        if enabled and documents and settings.pageindex_root_path:
            self._start_warmup_thread(documents)
        return self.get_warmup_status()

    def _start_warmup_thread(self, documents: list[DocumentSummary]) -> bool:
        with self._warmup_lock:
            if not self._warmup_enabled:
                return False
            if self._warmup_thread is not None and self._warmup_thread.is_alive():
                return False
            self._warmup_stop_requested = False
            self._warmup_thread = Thread(target=self._warm_documents, args=(documents,), daemon=True, name="pageindex-warmup")
            self._warmup_thread.start()
            return True

    def _warm_documents(self, documents: list[DocumentSummary]) -> None:
        try:
            for document in documents:
                with self._warmup_lock:
                    if self._warmup_stop_requested or not self._warmup_enabled:
                        break
                self.build_index(document)
        finally:
            with self._warmup_lock:
                self._warmup_thread = None

    def retrieve_snippets(self, document: DocumentSummary, query: str, top_k: int = 3) -> list[EvidenceSnippet]:
        index_dir = self._index_dir(document)
        if not index_dir.exists():
            return []

        tree_file = self._find_tree_file(index_dir)
        if not tree_file:
            return []

        try:
            tree_data = json.loads(tree_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

        terms = [term.lower() for term in query.split() if len(term) > 2]
        query_lower = query.lower()
        scored_nodes: list[tuple[int, dict]] = []
        for node in self._walk_nodes(tree_data):
            score = self._score_node(node, query_lower, terms)
            if score:
                scored_nodes.append((score, node))
        scored_nodes.sort(key=lambda item: item[0], reverse=True)

        results: list[EvidenceSnippet] = []
        for _, node in scored_nodes[:top_k]:
            start_page = int(node.get("start_index", 0)) + 1
            summary = str(node.get("summary", "")).strip() or str(node.get("title", "Relevant section"))
            results.append(
                EvidenceSnippet(
                    page=start_page,
                    section=str(node.get("title", "Relevant section")),
                    snippet=summary[:700],
                    retrieval_method="pageindex_tree",
                )
            )
        return results

    def _index_dir(self, document: DocumentSummary) -> Path:
        return settings.pageindex_dir / document.doc_id

    def _score_node(self, node: dict, query_lower: str, terms: list[str]) -> int:
        title = str(node.get("title", ""))
        summary = str(node.get("summary", ""))
        title_lower = title.lower()
        summary_lower = summary.lower()
        haystack = f"{title_lower} {summary_lower}"

        score = sum(title_lower.count(term) * 5 + summary_lower.count(term) for term in terms)
        if query_lower and query_lower in haystack:
            score += 20

        focus_phrases = [
            "precertification",
            "prior authorization",
            "criteria for initial approval",
            "initial approval",
            "medically necessary",
            "site of care",
            "utilization management",
            "coverage",
            "policy",
            "scope of policy",
        ]
        for phrase in focus_phrases:
            if phrase in query_lower and phrase in haystack:
                score += 12
            elif phrase in haystack:
                score += 3

        title_boosts = {
            "policy": 12,
            "scope of policy": 12,
            "criteria for initial approval": 18,
            "initial approval": 14,
            "prescriber specialties": 8,
            "continuation of therapy": 6,
        }
        for marker, boost in title_boosts.items():
            if marker in title_lower:
                score += boost

        title_penalties = [
            "references",
            "appendix",
            "background",
            "review history",
        ]
        for marker in title_penalties:
            if marker in title_lower:
                score -= 8

        start_index = int(node.get("start_index", 0) or 0)
        if start_index:
            score += max(0, 10 - min(start_index, 10))

        return max(score, 0)

    def _find_tree_file(self, index_dir: Path) -> Path | None:
        json_files = sorted(path for path in index_dir.rglob("*.json") if path.name.endswith("_structure.json"))
        return json_files[0] if json_files else None

    def _walk_nodes(self, node: object) -> list[dict]:
        if isinstance(node, list):
            items: list[dict] = []
            for child in node:
                items.extend(self._walk_nodes(child))
            return items
        if not isinstance(node, dict):
            return []
        items = [node] if any(key in node for key in ("title", "summary", "start_index")) else []
        for child in node.get("structure", []):
            items.extend(self._walk_nodes(child))
        for child in node.get("nodes", []):
            items.extend(self._walk_nodes(child))
        return items
