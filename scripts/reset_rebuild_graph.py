#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.core.config import settings
from backend.app.core.database import initialize_database
from backend.app.models.schemas import ChangeRequest
from backend.app.services.comparison_service import ComparisonService
from backend.app.services.document_service import DocumentService
from backend.app.services.graph_service import GraphService
from backend.app.services.pageindex_service import PageIndexService
from backend.app.services.policy_service import PolicyService


EXCLUDED_POLICY_TOKENS = [
    "opening ceremony",
    "summary-of-change",
    "summary of change",
    "policy updates",
    "update bulletin",
    "medical policy update bulletin",
    "provider-administered-preferred-products",
    "provider administered preferred products",
    "medical-policy-update-bulletin",
    "priority health 2026 mdl",
]

DRUG_HINTS = {
    "infliximab": "Infliximab",
    "ustekinumab": "Ustekinumab",
    "stelara": "Ustekinumab",
    "rituximab": "Rituximab",
    "denosumab": "Denosumab",
    "bevacizumab": "Bevacizumab",
    "bevecizumab": "Bevacizumab",
    "avastin": "Bevacizumab",
    "botulinum": "Botulinum Toxins",
}


def build_services() -> tuple[DocumentService, PolicyService, ComparisonService, GraphService]:
    settings.ensure_directories()
    if settings.sqlite_path.exists():
        settings.sqlite_path.unlink()
    initialize_database(settings.sqlite_path)

    for folder in [settings.extraction_dir, settings.cache_dir, settings.pageindex_dir]:
        folder.mkdir(parents=True, exist_ok=True)
        for file_path in folder.glob("*"):
            if file_path.is_file():
                file_path.unlink()
            elif file_path.is_dir():
                for nested in sorted(file_path.rglob("*"), reverse=True):
                    if nested.is_file():
                        nested.unlink()
                    elif nested.is_dir():
                        nested.rmdir()
                file_path.rmdir()

    graph_service = GraphService()
    graph_service.clear_graph()
    graph_service.initialize_schema()

    document_service = DocumentService()
    pageindex_service = PageIndexService()
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
    return document_service, policy_service, comparison_service, graph_service


def should_ingest(document) -> bool:
    if document.payer == "Unknown":
        return False
    name = re.sub(r"[\W_]+", " ", document.policy_name.lower()).strip()
    if any(token in name for token in EXCLUDED_POLICY_TOKENS):
        return False
    if document.document_pattern != "single_drug":
        return False
    return infer_drug_name(document) is not None


def infer_drug_name(document) -> str | None:
    haystack = f"{document.policy_name} {document.likely_drug or ''}".lower()
    for token, drug_name in DRUG_HINTS.items():
        if token in haystack:
            return drug_name
    return None


def main() -> None:
    document_service, policy_service, comparison_service, graph_service = build_services()
    documents = document_service.refresh_documents()
    ingested_records = []
    skipped_documents = []
    failures = []

    for document in documents:
        if not should_ingest(document):
            skipped_documents.append(
                {
                    "doc_id": document.doc_id,
                    "payer": document.payer,
                    "policy_name": document.policy_name,
                    "document_pattern": document.document_pattern,
                }
            )
            continue
        drug_name = infer_drug_name(document)
        if not drug_name:
            continue
        question = (
            f"Summarize coverage status, prior authorization criteria, step therapy, "
            f"site of care, covered indications, effective date, and relevant codes for {drug_name}."
        )
        print(f"Ingesting {document.doc_id} [{document.payer}] for {drug_name}...", flush=True)
        try:
            record = policy_service.answer_for_document(document, drug_name, question)
            ingested_records.append(record.model_dump())
        except Exception as exc:
            failures.append({"doc_id": document.doc_id, "error": str(exc)})
            print(f"Failed {document.doc_id}: {exc}", flush=True)

    version_groups = defaultdict(list)
    for document in documents:
        if document.version_group:
            version_groups[document.version_group].append(document)

    diffs = []
    for group, items in version_groups.items():
        if len(items) < 2:
            continue
        if not all(should_ingest(item) for item in items):
            continue
        ordered = sorted(items, key=lambda item: item.version_label)
        print(f"Diffing {ordered[0].doc_id} -> {ordered[-1].doc_id}...", flush=True)
        try:
            response = comparison_service.diff_versions(
                ChangeRequest(
                    drug_name=infer_drug_name(ordered[-1]) or ordered[-1].likely_drug or ordered[-1].policy_name,
                    question="What changed between these policy versions?",
                    old_doc_id=ordered[0].doc_id,
                    new_doc_id=ordered[-1].doc_id,
                )
            )
            diffs.append(response.model_dump())
        except Exception as exc:
            failures.append({"version_group": group, "error": str(exc)})
            print(f"Failed diff {group}: {exc}", flush=True)

    payer_names = []
    constraint_names = []
    label_counts = []
    if graph_service._driver:
        with graph_service._driver.session(database=settings.neo4j_database) as session:
            payer_names = [row["name"] for row in session.run("MATCH (p:Payer) RETURN p.name AS name ORDER BY name").data()]
            constraint_names = [row["name"] for row in session.run("SHOW CONSTRAINTS").data()]
            label_counts = session.run(
                "MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY count DESC"
            ).data()

    output = {
        "graph_status": graph_service.get_status().model_dump(),
        "constraints": constraint_names,
        "payer_names": payer_names,
        "label_counts": label_counts,
        "ingested_record_count": len(ingested_records),
        "diff_count": len(diffs),
        "skipped_documents": skipped_documents,
        "failures": failures,
        "ingested_records": ingested_records,
        "diffs": diffs,
    }
    output_path = settings.storage_dir / "graph_rebuild_results.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"output_file": str(output_path.resolve()), **output["graph_status"], "payer_names": payer_names}, indent=2))


if __name__ == "__main__":
    main()
