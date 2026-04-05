#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.core.config import settings
from backend.app.core.database import initialize_database
from backend.app.models.schemas import AskRequest, ChangeRequest, CompareRequest
from backend.app.services.comparison_service import ComparisonService
from backend.app.services.document_service import DocumentService
from backend.app.services.graph_service import GraphService
from backend.app.services.pageindex_service import PageIndexService
from backend.app.services.policy_service import PolicyService


TEST_CASES = [
    {
        "id": "compare_infliximab",
        "kind": "compare",
        "drug_name": "Infliximab",
        "question": "How do these payers cover infliximab under the medical benefit?",
        "payer_filters": ["Aetna", "Cigna", "UnitedHealthcare"],
    },
    {
        "id": "compare_ustekinumab",
        "kind": "compare",
        "drug_name": "Ustekinumab",
        "question": "How do these payers cover ustekinumab under the medical benefit?",
        "payer_filters": ["Aetna", "Cigna", "UnitedHealthcare"],
    },
    {
        "id": "ask_rituximab_cigna",
        "kind": "ask",
        "drug_name": "Rituximab",
        "question": "What prior authorization criteria apply for rituximab for non-oncology indications?",
        "payer_filters": ["Cigna"],
    },
    {
        "id": "ask_denosumab_emblem",
        "kind": "ask",
        "drug_name": "Denosumab",
        "question": "What does the policy say about coverage and HCPCS coding for denosumab?",
        "payer_filters": ["EmblemHealth"],
    },
    {
        "id": "ask_bevacizumab_florida_blue",
        "kind": "ask",
        "drug_name": "Bevacizumab",
        "question": "What are the coverage criteria and access status for bevacizumab?",
        "payer_filters": ["Florida Blue", "BCBS NC"],
    },
    {
        "id": "ask_botulinum_uhc",
        "kind": "ask",
        "drug_name": "Botulinum Toxins",
        "question": "What diagnosis-specific criteria and prior authorization requirements apply?",
        "payer_filters": ["UnitedHealthcare"],
    },
    {
        "id": "change_infliximab_uhc_versions",
        "kind": "changes",
        "drug_name": "Infliximab",
        "question": "What changed between these infliximab policy versions?",
        "old_doc_id": "infliximab-remicade-inflectra",
        "new_doc_id": "infliximab-remicade-inflectra-02012026",
    },
]


def build_services() -> tuple[DocumentService, PolicyService, ComparisonService]:
    settings.ensure_directories()
    initialize_database(settings.sqlite_path)
    document_service = DocumentService()
    graph_service = GraphService()
    graph_service.initialize_schema()
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
    return document_service, policy_service, comparison_service


def main() -> None:
    document_service, policy_service, comparison_service = build_services()
    documents = document_service.refresh_documents()
    graph_status = GraphService().get_status().model_dump()

    results: list[dict] = []
    for case in TEST_CASES:
        if case["kind"] == "ask":
            response = policy_service.answer_question(
                AskRequest(
                    drug_name=case["drug_name"],
                    question=case["question"],
                    payer_filters=case.get("payer_filters", []),
                )
            )
            payload = response.model_dump()
        elif case["kind"] == "compare":
            response = comparison_service.compare(
                CompareRequest(
                    drug_name=case["drug_name"],
                    question=case["question"],
                    payer_filters=case.get("payer_filters", []),
                )
            )
            payload = response.model_dump()
        else:
            response = comparison_service.diff_versions(
                ChangeRequest(
                    drug_name=case["drug_name"],
                    question=case["question"],
                    old_doc_id=case["old_doc_id"],
                    new_doc_id=case["new_doc_id"],
                )
            )
            payload = response.model_dump()
        results.append({"case": case, "result": payload})

    manifest = {
        "graph_status": graph_status,
        "document_count": len(documents),
        "documents": [doc.model_dump() for doc in documents],
        "test_cases": TEST_CASES,
    }
    (settings.storage_dir / "test_cases.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (settings.storage_dir / "ingestion_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    summary = {
        "graph_status": graph_status,
        "document_count": len(documents),
        "result_count": len(results),
        "result_file": str((settings.storage_dir / "ingestion_results.json").resolve()),
        "test_case_file": str((settings.storage_dir / "test_cases.json").resolve()),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
