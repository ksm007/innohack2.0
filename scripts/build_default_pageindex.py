#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.services.document_service import DocumentService
from backend.app.services.pageindex_service import PageIndexService


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PageIndex artifacts for the local PDF corpus.")
    parser.add_argument("--force", action="store_true", help="Rebuild even if a cached tree already exists.")
    parser.add_argument("--doc-id", action="append", default=[], help="Limit the build to one or more specific doc_ids.")
    args = parser.parse_args()

    document_service = DocumentService()
    pageindex_service = PageIndexService()
    documents = document_service.refresh_documents()

    if args.doc_id:
        requested = set(args.doc_id)
        documents = [document for document in documents if document.doc_id in requested]

    results = pageindex_service.build_indexes(documents, force=args.force)
    print(
        json.dumps(
            {
                "document_count": len(documents),
                "results": [result.model_dump() for result in results],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
