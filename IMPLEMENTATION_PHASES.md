# Implementation Phases

## Phase 1: foundation and local runtime

- Create `.venv` and pin backend dependencies in `backend/requirements.txt`
- Add FastAPI skeleton and local SQLite initialization
- Normalize the source document folder around the provided `docs/*.pdf`
- Add environment configuration with `.env.example`
- Add local storage directories for cache, PageIndex output, and structured extraction JSON

Deliverable:
A bootable backend with document discovery and persistence.

## Phase 2: ingestion and document understanding

- Discover all policy PDFs from `docs/`
- Infer payer, likely drug, version label, and single-drug vs multi-drug pattern from filename and extracted text
- Cache raw PDF text locally
- Persist document metadata in SQLite
- Expose `GET /api/documents` for the frontend

Deliverable:
A browsable local corpus with metadata and version grouping.

## Phase 3: PageIndex integration and evidence retrieval

- Wire a PageIndex adapter around a local `PAGEINDEX_ROOT`
- Generate tree indexes per document and store artifacts in `storage/pageindex/`
- Read generated tree JSON when available
- Fall back to local keyword/page search when an index is missing
- Return top evidence snippets with page numbers and retrieval method labels

Deliverable:
Explainable retrieval without a vector database.

## Phase 4: OpenAI extraction and analyst Q&A

- Send retrieved snippets to OpenAI for structured field extraction
- Enforce fallback semantics: `Answered`, `Partial`, `Review required`, `No policy found`, `Not covered`
- Store structured outputs locally in SQLite and JSON
- Expose `POST /api/ask`
- Show answer, structured fields, confidence, and evidence in React

Deliverable:
Analyst-first Q&A with citations.

## Phase 5: cross-payer comparison

- Run one extraction pass per payer for a selected drug
- Normalize the result set into a compare table
- Highlight differences in coverage, PA, step therapy, site of care, effective date, and status
- Support export to CSV or copyable markdown in the UI
- Expose `POST /api/compare`
- Persist payer, policy, version, requirement, and evidence relationships in Neo4j for graph-native summaries

Deliverable:
The highest-value MVP feature from the Q&A.

## Phase 6: version diff and change classification

- Pair old/new policy versions for the same drug or policy family
- Compare extracted fields instead of diffing raw text only
- Mark changes as `meaningful` or `cosmetic_admin`
- Expose `POST /api/changes`
- Render changed fields with old value, new value, and evidence references
- Use Neo4j relationships to summarize added/removed indications and requirement types between versions

Deliverable:
Change tracking that reflects clinical and access differences instead of formatting noise.

## Phase 7: demo polish

- Add canned prompts and recommended demo flows
- Improve loading/error states in the UI
- Pre-index a small set of high-value PDFs
- Validate at least one single-drug and one multi-drug document path
- Rehearse the story: Ask -> Compare -> Changes -> Evidence

Deliverable:
A judge-ready demo aligned to the hackathon scoring criteria.
