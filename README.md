# DOC Parsers

DOC Parsers is a local-first policy intelligence app for payer PDF analysis.

It is built for three main workflows:
- `Ask`: answer one payer-specific policy question with evidence
- `Compare`: compare multiple payers for the same drug
- `Changes`: review version-to-version policy deltas

The stack in this repo:
- `FastAPI` for API orchestration
- `React + Vite` for the frontend
- `OpenAI API` for structured extraction and summarization
- `PageIndex` for section-aware PDF retrieval
- `Neo4j` for graph relationships
- `SQLite + local files` for local-first storage and caching

## Project Layout

```text
backend/            FastAPI app
frontend/           React app
docs/               source and uploaded PDFs
prompts/            prompt templates
scripts/            run helpers and corpus utilities
storage/            SQLite DB, cache, PageIndex artifacts, saved outputs
PageIndex/          local clone / checkout of the PageIndex project
```

## What Is Stored Locally

- `docs/`
  - payer policy PDFs, including uploaded PDFs
- `storage/anton_rx_track.db`
  - local SQLite database
- `storage/cache/`
  - cached PDF text / retrieval artifacts
- `storage/pageindex/`
  - PageIndex outputs per document
- `storage/*.json`
  - saved ingestion and rebuild outputs used for debugging/demo support

Neo4j is the only non-local data layer when configured.

## Prerequisites

- Python `3.11+`
- Node.js `18+`
- npm
- a project-local Python virtual environment at `.venv`
- optional but recommended:
  - OpenAI API key
  - Neo4j instance
  - local PageIndex repo in `PageIndex/` or elsewhere on disk

## 1. Create The Python Virtual Environment

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

## 2. Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

## 3. Configure Environment

Copy the template:

```bash
cp .env.example .env
```

Set at least:

```env
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4.1-mini

NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j

PAGEINDEX_ROOT=/absolute/path/to/PageIndex
PAGEINDEX_PYTHON=python3
PAGEINDEX_WARMUP_ON_STARTUP=false

BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
FRONTEND_API_URL=http://127.0.0.1:8000/api
```

Notes:
- `PAGEINDEX_ROOT` should point to the local PageIndex repo directory that contains `run_pageindex.py`
- keep `PAGEINDEX_WARMUP_ON_STARTUP=false` unless you explicitly want background indexing on backend startup

## 4. Install PageIndex Requirements

If you are using PageIndex retrieval, install its dependencies into the same `.venv`:

```bash
source .venv/bin/activate
pip install -r PageIndex/requirements.txt
```

If your PageIndex checkout is not in `./PageIndex`, install requirements from your chosen path instead.

## 5. Run The App

### Backend

```bash
bash scripts/run_backend.sh
```

This starts FastAPI on:

```text
http://127.0.0.1:8000
```

### Frontend

In a second terminal:

```bash
bash scripts/run_frontend.sh
```

This starts the Vite dev server, usually on:

```text
http://127.0.0.1:5173
```

## Manual Run Commands

If you do not want to use the helper scripts:

### Backend

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm run dev
```

## Upload And Ingest PDFs

You can add new PDFs in two ways:

### Option A: UI Upload

- open the `Upload` tab in the frontend
- select a PDF
- click `Upload PDF`

The file is saved into `docs/`.

### Option B: Manual Copy

Place PDFs directly into:

```text
docs/
```

Then restart the backend or refresh the document list in the running app.

## Warm PageIndex

PageIndex is used to build section-aware retrieval artifacts for PDFs.

### Warm from the UI

- use the `Warm current corpus` button

### Warm all documents from the CLI

```bash
source .venv/bin/activate
python scripts/build_pageindex_defaults.py
```

### Warm one specific document

```bash
python scripts/build_pageindex_defaults.py --doc-id 'your_doc_id_here'
```

### Force rebuild

```bash
python scripts/build_pageindex_defaults.py --force
```

## Build / Rebuild Helper Scripts

### Ingest and test the current corpus

```bash
source .venv/bin/activate
python scripts/ingest_corpus.py
```

### Reset and rebuild graph-backed corpus state

```bash
source .venv/bin/activate
python scripts/reset_rebuild_graph.py
```

## Main API Routes

- `GET /api/health`
- `GET /api/graph/status`
- `GET /api/documents`
- `GET /api/documents/{doc_id}/pdf`
- `POST /api/documents/upload`
- `POST /api/index/build`
- `GET /api/index/settings`
- `POST /api/index/settings`
- `POST /api/ask`
- `POST /api/compare`
- `POST /api/changes`
- `POST /api/evidence/summary`
- `GET /api/history`
- `GET /api/history/{history_id}`
- `DELETE /api/history`
- `DELETE /api/history/{history_id}`

## Demo Flow

Recommended order for demo:

1. `Home`
2. `Ask`
3. `Compare`
4. `Changes`
5. `History`

Supporting files:
- [3_MINUTE_DEMO_SCRIPT.md](/Users/ksm007/Desktop/Projects/innohack2.0/3_MINUTE_DEMO_SCRIPT.md)
- [ARCHITECTURE_DIAGRAM.md](/Users/ksm007/Desktop/Projects/innohack2.0/ARCHITECTURE_DIAGRAM.md)
- [IMPLEMENTATION_PHASES.md](/Users/ksm007/Desktop/Projects/innohack2.0/IMPLEMENTATION_PHASES.md)

## Troubleshooting

### Upload fails with multipart/form-data error

Install backend dependencies again:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### PageIndex build fails

Check:
- `PAGEINDEX_ROOT` is correct
- PageIndex requirements are installed
- your OpenAI API key is set

### Neo4j graph data not appearing

Check:
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- the instance is reachable

### Frontend still shows old local state

Hard refresh the browser, or clear site localStorage in dev tools.

## Status

This repo is demo-ready for:
- evidence-backed policy Q&A
- cross-payer policy comparison
- version-aware change review
- upload + local corpus management

The strongest production-style differentiators are:
- PageIndex-backed section retrieval
- structured policy extraction
- graph-backed cross-document intelligence
- local-first persistence and auditability
