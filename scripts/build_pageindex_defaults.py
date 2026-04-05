#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.core.config import settings
from backend.app.core.database import initialize_database
from backend.app.services.document_service import DocumentService
from backend.app.services.pageindex_service import PageIndexService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm PageIndex trees for local PDFs.")
    parser.add_argument("--force", action="store_true", help="Rebuild even if a cached tree already exists.")
    parser.add_argument("--doc-id", action="append", dest="doc_ids", default=[], help="Limit build to one or more doc_ids.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings.ensure_directories()
    initialize_database(settings.sqlite_path)

    document_service = DocumentService()
    pageindex_service = PageIndexService()
    documents = document_service.refresh_documents()
    if args.doc_ids:
        target_ids = set(args.doc_ids)
        documents = [document for document in documents if document.doc_id in target_ids]

    total = len(documents)
    results = []
    print(f"Starting PageIndex warmup for {total} document(s). force={args.force}", flush=True)

    for index, document in enumerate(documents, start=1):
        started_at = time.perf_counter()
        print(f"[{index}/{total}] Building {document.doc_id}...", flush=True)
        result = pageindex_service.build_index(document, force=args.force)
        elapsed = time.perf_counter() - started_at
        print(f"[{index}/{total}] {result.status.upper()} {document.doc_id} ({elapsed:.1f}s)", flush=True)
        results.append(result)

    summary = {
        "document_count": total,
        "status_counts": {},
        "results": [result.model_dump() for result in results],
    }
    for result in results:
        summary["status_counts"][result.status] = summary["status_counts"].get(result.status, 0) + 1

    output_path = settings.storage_dir / "pageindex_build_results.json"
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_file": str(output_path.resolve()),
                "document_count": total,
                "status_counts": summary["status_counts"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
