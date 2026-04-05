# Anton Rx Track

Local-first hackathon scaffold for the Anton Rx medical-benefit policy tracker using:

- FastAPI for ingestion, retrieval orchestration, extraction, comparison, and change detection
- React for the analyst-facing UI
- OpenAI API for structured extraction and answer synthesis
- PageIndex for vectorless document indexing and reasoning-oriented retrieval
- Neo4j for graph-native policy, requirement, evidence, and version relationships
- SQLite and local files for all runtime data storage

## Why this architecture

The problem statement and Q&A prioritize:

- daily analyst Q&A
- side-by-side comparison for one drug across payers
- version-to-version change tracking
- evidence-backed answers with page citations
- support for both single-drug PDFs and multi-drug mega-documents

This scaffold is designed around those constraints and keeps the system local by default.

## Project layout

```text
backend/            FastAPI app
frontend/           React app
docs/               source payer policy PDFs
prompts/            extraction prompts
storage/            SQLite DB + cached text + PageIndex artifacts
scripts/            local run helpers
```

## Local storage model

- `storage/anton_rx_track.db`: document metadata, extraction runs, compare snapshots, PageIndex runs
- `storage/cache/`: cached raw PDF text extraction
- `storage/extractions/`: structured JSON outputs for debugging and demos
- `storage/pageindex/`: PageIndex tree outputs per document

SQLite remains the local cache/system-of-record for raw runs. Neo4j is used as an optional analytical relationship layer when configured.

## Python environment

The project uses a local virtual environment at `.venv/`.

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

## Configure environment

```bash
cp .env.example .env
```

Fill in:

- `OPENAI_API_KEY`
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
- `PAGEINDEX_ROOT` pointing to a local clone of `https://github.com/VectifyAI/PageIndex`
- optional: `PAGEINDEX_WARMUP_ON_STARTUP=false` by default; turn it on only if you want the backend to warm missing PageIndex trees for all PDFs on startup

PageIndex usage is based on the project README, which describes self-hosting the repo locally, installing its requirements, and running `python run_pageindex.py --pdf_path /path/to/document.pdf` to generate a tree index. In this app, PageIndex is invoked with the same Python interpreter as the running backend by default so it stays inside the project `.venv`.

`PAGEINDEX_WARMUP_ON_STARTUP` means background indexing: when enabled, the backend starts a background job after startup that walks the discovered PDFs and builds any missing PageIndex trees. This makes later retrieval faster, but it also increases startup work, OpenAI usage, and cost. Keep it off unless you explicitly want automatic warming.

## Prebuild PageIndex for all docs

To warm cached PageIndex trees for every PDF already in `docs/`:

```bash
source .venv/bin/activate
python scripts/build_default_pageindex.py
```

Existing tree files are reused automatically. Use `--force` to rebuild or `--doc-id <doc_id>` to target one file.

## Run backend

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

## Run frontend

```bash
cd frontend
npm install
npm run dev
```

## Main API routes

- `GET /api/health`
- `GET /api/graph/status`
- `GET /api/documents`
- `POST /api/index/build`
- `POST /api/ask`
- `POST /api/compare`
- `POST /api/changes`

## Delivery phases

Implementation phases are documented in [IMPLEMENTATION_PHASES.md](/Users/ksm007/Desktop/Projects/innohack2.0/IMPLEMENTATION_PHASES.md).
