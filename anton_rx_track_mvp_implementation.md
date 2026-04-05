# Anton Rx Track — Revised MVP Implementation Document

## 1. Executive summary

This document defines a **5-hour MVP** for **Anton Rx Track**, an AI-powered system to ingest, parse, normalize, and compare **medical benefit drug policies** across payers. The MVP is scoped for the hackathon and optimized for the stated judging criteria: **problem understanding, technical implementation, usability, completeness, and wow factor**. It focuses on **commercial medical-benefit policies**, **daily analyst Q&A**, **cross-payer comparison for a single drug**, and **version-to-version change tracking**.

The primary user is a **market access analyst or formulary strategist** who currently reads payer PDFs manually to answer questions like:
- Which plans cover Drug X?
- What prior authorization criteria does Payer Y require?
- How do policies differ across payers?
- What changed between policy versions?

The MVP should not attempt to be a full production system. Instead, it should prove the concept with:
- 3 to 5 policies from 2 to 3 payers
- 1 or 2 therapeutic areas, preferably oncology or immunology
- evidence-backed answers
- a normalized comparison table
- a simple diff view
- explicit fallback states such as **No policy found**, **Partial**, and **Review required**.

---

## 2. Problem framing

### 2.1 What makes this hard

The problem statement says there is **no centralized, standardized source** for tracking medical-benefit drug coverage, clinical criteria, or differences across plans. Payers publish policies in different formats, structures, and update cadences. Analysts must manually find documents, read them, normalize the content mentally, and keep up with changes.

The Q&A identifies three layers of pain:
1. **Discovery** — analysts must manually find the right document on each payer site.
2. **Extraction and comparison** — policies differ in format and terminology.
3. **Change tracking** — policies can change any time, sometimes without notice.

### 2.2 What success looks like

A successful prototype helps a non-technical analyst quickly answer a question like:
- “Does Cigna cover Rituxan for lupus?”
- “What step therapy does UHC require for Humira?”
- “How do Cigna and UHC differ on Drug X?”
- “What changed between the latest and previous version?”

---

## 3. Target user and workflow

### 3.1 Primary user

The primary user should be treated as a **market access analyst or formulary strategist** at a company like Anton Rx. They are domain experts, not developers, and they currently do this work manually by reading PDFs.

### 3.2 Usage frequency

The Q&A says:
- **Daily** for Q&A
- **Ongoing / alerting-oriented** for change tracking
- **Weekly or monthly** for cross-payer comparison in strategy work.

This means the product should open on **Ask/Search**, not on a technical admin screen.

---

## 4. MVP scope

### 4.1 In scope

- Commercial policies only
- Medical benefit only
- 3 to 5 policy documents
- 2 to 3 payers
- 1 to 2 therapeutic areas, ideally oncology or immunology
- Search/Q&A for one drug
- Side-by-side comparison across payers
- Version diff for one policy
- Evidence view with page citations
- Simple export such as CSV or copyable text.

### 4.2 Out of scope

- User authentication
- Medicare/Medicaid support
- Pharmacy-benefit reconciliation
- Full automated multi-payer crawling
- Full graph DB implementation
- Full production OCR pipeline
- Member-level workflows or prior auth automation.

---

## 5. Product priorities

### Priority 1: Q&A
The Q&A document explicitly says Q&A and change tracking are tied for first priority. Daily analyst questions are the core use case.

### Priority 2: Change tracking
The most compelling bonus feature is comparing a previous version to the newest version and surfacing **meaningful clinical or coverage changes** versus cosmetic edits.

### Priority 3: Cross-payer comparison
The single most valuable MVP feature is a normalized side-by-side comparison of coverage criteria for a single drug across multiple payers.

---

## 6. High-level architecture

```text
Sample policy PDFs / HTML
    -> document loader
    -> parser / text extraction
    -> section segmentation
    -> retrieval layer
    -> structured extraction
    -> normalized JSON store
    -> UI: Ask | Compare | Changes | Evidence | Export
```

This architecture matches the hackathon expectation of showing **ingestion -> extraction -> comparison -> interface**.

---

## 7. Why PageIndex fits this solution

PageIndex is useful in the retrieval layer, especially for long and messy documents. In this problem, policies vary widely:
- some payers publish one PDF per drug,
- some use large multi-drug documents,
- some use portal-like formats.

For the MVP, PageIndex can be used to:
- retrieve the most relevant pages or sections for a drug query,
- support evidence-backed Q&A,
- improve navigation inside long policy PDFs,
- retrieve relevant sections before extraction.

For a 5-hour build, it is reasonable to use PageIndex only for **evidence retrieval**, not as the full system of record.

---

## 8. Section segmentation is mandatory

The Q&A explicitly says the system must handle both:
- **single-drug documents**
- **mega-documents covering multiple drugs**.

Therefore the parser should first classify documents as:
- `single_drug`
- `multi_drug`

### 8.1 Segmentation rules for multi-drug documents
Use simple heuristics:
- split on strong headings
- split on repeated drug names
- split on page-level title changes
- detect sections with clinical criteria or code tables
- assign each section to one or more candidate drugs

If section ownership is ambiguous, do not force a final answer; mark the result as **Review required**.

---

## 9. Core data model

Use JSON or SQLite for the MVP.

```json
{
  "doc_id": "",
  "payer": "",
  "policy_name": "",
  "policy_type": "",
  "document_pattern": "single_drug | multi_drug",
  "line_of_business": "commercial",
  "effective_date": "",
  "drug_name_brand": "",
  "drug_name_generic": "",
  "drug_category": "",
  "access_status": "",
  "preferred_status_rank": "",
  "covered_indications": [],
  "coverage_status": "",
  "prior_auth_required": "",
  "prior_auth_criteria": "",
  "step_therapy": "",
  "site_of_care": "",
  "dosing_quantity_limits": "",
  "hcpcs_codes": [],
  "biosimilar_reference_relationships": [],
  "evidence": [
    {
      "page": 0,
      "section": "",
      "snippet": ""
    }
  ],
  "confidence": "high | medium | low",
  "status": "Answered | Partial | Review required | No policy found | Not covered"
}
```

### Why these fields
The Q&A prioritizes:
- drug name
- drug category
- access status within category
- covered indications
- prior auth yes/no and criteria
- step therapy
- site of care
- dosing/quantity limits
- effective date.

Drug category and access status are especially important because they influence rebate economics.

---

## 10. Status model and fallback semantics

These labels must be visible in the UI.

### 10.1 Answered
There is enough evidence to provide a clear answer.

### 10.2 Partial
Relevant evidence exists, but one or more critical fields are missing or weak.

### 10.3 Review required
Use when:
- a multi-drug section is ambiguous,
- two snippets conflict,
- two versions disagree and cannot be cleanly resolved.

### 10.4 No policy found
Use when the drug does not appear in the available document set.

### 10.5 Not covered
Use only when the policy explicitly states the drug is non-covered.

The Q&A explicitly distinguishes **Not covered** from **No policy exists / no policy found**, and says these should not be conflated.

---

## 11. Retrieval design

### 11.1 Query templates
Use a small set of templated queries:
- `Find coverage criteria for {drug_name}`
- `Find prior authorization requirements for {drug_name}`
- `Find step therapy requirements for {drug_name}`
- `Find site of care requirements for {drug_name}`
- `Find revision history for {drug_name}`

### 11.2 Retrieval flow
1. Choose document(s) based on payer filter.
2. If the doc is multi-drug, segment first.
3. Retrieve top 2 to 3 candidate snippets.
4. Send snippets to extractor.
5. Save the snippets as evidence.

### 11.3 Retrieval fallback
If retrieval confidence is weak:
1. do keyword search on raw text,
2. search drug name, generic/brand variants, HCPCS/J-codes if present,
3. search common phrases such as `coverage criteria`, `prior authorization`, `step therapy`, `site of care`, `revision history`,
4. if still weak, return `Partial` or `No policy found`.

---

## 12. Extraction design

### 12.1 Extraction strategy
Use a hybrid approach:
- regex / rules for effective dates, yes-no fields, and obvious codes,
- LLM extraction for free-text fields such as diagnosis criteria and step therapy.

### 12.2 MVP extraction fields
Extract these first:
- drug name
- indication
- prior auth required
- prior auth criteria
- step therapy
- site of care
- effective date.

If time remains, add:
- drug category
- access status
- dosing limits
- HCPCS code
- biosimilar relationships.

### 12.3 Extraction prompt
Store this in `prompts/extract_policy_fields.txt`:

```text
You are extracting structured facts from medical-benefit payer policy snippets.

Return JSON with exactly these keys:
payer
policy_name
document_pattern
effective_date
drug_name_brand
drug_name_generic
drug_category
access_status
preferred_status_rank
covered_indications
coverage_status
prior_auth_required
prior_auth_criteria
step_therapy
site_of_care
dosing_quantity_limits
hcpcs_codes
biosimilar_reference_relationships
confidence
status
evidence

Rules:
- Use only the provided snippets.
- If a field is unclear, return "unknown".
- If no drug-specific policy language is found, return status = "No policy found".
- If the policy explicitly denies coverage, return status = "Not covered".
- If the snippets conflict or section mapping is ambiguous, return status = "Review required".
- Never guess.
```

---

## 13. Compare logic

The key MVP view is a normalized table for one drug across multiple payers.

### 13.1 Table columns
- Payer
- Drug
- Coverage
- Prior Auth
- Step Therapy
- Site of Care
- Effective Date
- Access Status
- Confidence
- Status

### 13.2 Compare algorithm
For each selected payer:
1. retrieve evidence,
2. extract fields,
3. normalize values,
4. render one row per payer.

### 13.3 Export
Provide a simple CSV export or copyable markdown table. The Q&A says analysts frequently need to share comparison results in reports, presentations, or emails.

---

## 14. Change tracking design

### 14.1 Goal
Compare a previous version of a policy with the latest version and identify:
- meaningful clinical or coverage changes,
- likely cosmetic or administrative changes.

### 14.2 Diff method
Field-by-field compare:
- coverage_status
- prior_auth_required
- prior_auth_criteria
- step_therapy
- site_of_care
- covered_indications
- effective_date

### 14.3 Change classification
Classify as **meaningful** if a change affects:
- coverage status
- indication eligibility
- PA requirements
- step therapy
- site of care
- dosage/quantity limit

Classify as **cosmetic/admin** if it affects:
- formatting only
- references only
- date changes without criteria change
- section renumbering

### 14.4 Output
Show:
- old value
- new value
- change label
- evidence snippets for each version

---

## 15. UI specification

The daily use case is Q&A, so the first tab should be **Ask**.

### 15.1 Sidebar
- select payer(s)
- select document(s)
- select drug
- select question type
- choose compare mode or version diff

### 15.2 Ask tab
Display:
- direct answer
- structured fields
- confidence badge
- status badge
- top evidence snippets

### 15.3 Compare tab
Display:
- normalized table across payers
- highlighted differences
- export button

### 15.4 Changes tab
Display:
- old vs new values
- changed fields only
- meaningful vs cosmetic labels

### 15.5 Evidence tab
Display:
- document name
- page
- section
- snippet
- optionally page image preview later

---

## 16. Demo plan

A strong demo should show:
1. automated or semi-automated retrieval from multiple policy documents,
2. support for different document formats,
3. a clean comparison view understandable to a non-technical user.

### Recommended demo script
1. “Our target user is a market access analyst who currently reads payer PDFs manually.”
2. “We focused on commercial medical-benefit policies only.” fileciteturn1file2L54-L58
3. Ask a drug question in the Ask tab.
4. Show evidence-backed answer.
5. Open Compare and show payer differences.
6. Open Changes and show old vs new.
7. Highlight `No policy found` vs `Not covered`.

---

## 17. Recommended folder structure

```text
anton-rx-track/
  app.py
  requirements.txt
  README.md

  docs/
    payer_a_policy_v1.pdf
    payer_a_policy_v2.pdf
    payer_b_policy_v1.pdf
    payer_c_multi_drug.pdf

  data/
    extracted_facts.json
    doc_metadata.json

  prompts/
    extract_policy_fields.txt
    summarize_diff.txt

  src/
    config.py
    document_loader.py
    segmenter.py
    retriever.py
    extractor.py
    comparer.py
    diff_engine.py
    fallback.py
    export_utils.py
    ui_helpers.py
```

---

## 18. Module responsibilities

### `document_loader.py`
- load PDF metadata
- classify payer and version
- detect likely single-drug vs multi-drug pattern

### `segmenter.py`
- split multi-drug documents into candidate sections
- assign candidate drug names to sections

### `retriever.py`
- wrap PageIndex usage
- retrieve top evidence snippets

### `extractor.py`
- extract structured fields
- merge rule-based and LLM output

### `comparer.py`
- build cross-payer comparison rows

### `diff_engine.py`
- compare versions
- classify meaningful vs cosmetic changes

### `fallback.py`
- determine Answered / Partial / Review required / No policy found / Not covered

### `export_utils.py`
- export compare table to CSV
- copyable markdown or text summary

---

## 19. Function signatures

```python
def load_documents(doc_dir: str) -> list[dict]: ...
def classify_document_pattern(text: str) -> str: ...
def segment_document(doc_path: str) -> list[dict]: ...
def retrieve_relevant_snippets(doc_path: str, query: str, top_k: int = 3) -> list[dict]: ...
def extract_policy_fields(doc_id: str, drug_name: str, snippets: list[dict]) -> dict: ...
def compare_policies(records: list[dict]) -> list[dict]: ...
def diff_policy_versions(old_record: dict, new_record: dict) -> dict: ...
def determine_status(extracted: dict, snippets: list[dict]) -> str: ...
def export_comparison_csv(rows: list[dict], output_path: str) -> str: ...
```

---

## 20. Implementation order

### Phase 1: first 60 to 90 minutes
- create folder structure
- place 3 to 5 policies in `docs/`
- build document loader
- build a simple text extraction path
- render raw snippets in Streamlit

### Phase 2: next 60 minutes
- add retrieval
- add query templates
- show top snippets with page numbers

### Phase 3: next 60 minutes
- extract top six fields
- show Ask tab with direct answer + evidence

### Phase 4: next 45 minutes
- build Compare tab
- export to CSV

### Phase 5: next 45 minutes
- build Changes tab
- classify meaningful vs cosmetic

### Phase 6: final 30 minutes
- polish fallback states
- hardcode sample questions
- rehearse demo

---

## 21. Minimal pseudocode

### `document_loader.py`

```python
from pathlib import Path

def load_documents(doc_dir: str):
    docs = []
    for path in Path(doc_dir).glob("*.pdf"):
        docs.append({
            "doc_id": path.stem,
            "path": str(path),
            "payer": infer_payer(path.stem),
            "version_label": infer_version(path.stem)
        })
    return docs
```

### `retriever.py`

```python
def retrieve_relevant_snippets(doc_path: str, query: str, top_k: int = 3):
    # Use PageIndex or fallback keyword search
    # Return list of dicts:
    # [{"page": 4, "section": "Coverage Criteria", "snippet": "..."}]
    return []
```

### `extractor.py`

```python
def extract_policy_fields(doc_id: str, drug_name: str, snippets: list):
    return {
        "doc_id": doc_id,
        "drug_name_brand": drug_name,
        "drug_name_generic": "unknown",
        "coverage_status": "unknown",
        "prior_auth_required": "unknown",
        "prior_auth_criteria": "unknown",
        "step_therapy": "unknown",
        "site_of_care": "unknown",
        "effective_date": "unknown",
        "confidence": "low",
        "status": "Partial",
        "evidence": snippets
    }
```

### `comparer.py`

```python
def compare_policies(records: list[dict]):
    rows = []
    for r in records:
        rows.append({
            "payer": r.get("payer"),
            "drug": r.get("drug_name_brand"),
            "coverage": r.get("coverage_status"),
            "prior_auth": r.get("prior_auth_required"),
            "step_therapy": r.get("step_therapy"),
            "site_of_care": r.get("site_of_care"),
            "effective_date": r.get("effective_date"),
            "access_status": r.get("access_status"),
            "status": r.get("status")
        })
    return rows
```

### `diff_engine.py`

```python
MEANINGFUL_FIELDS = {
    "coverage_status",
    "prior_auth_required",
    "prior_auth_criteria",
    "step_therapy",
    "site_of_care",
    "covered_indications",
    "dosing_quantity_limits"
}

def diff_policy_versions(old_record: dict, new_record: dict):
    diffs = []
    for key in set(old_record.keys()).intersection(new_record.keys()):
        if old_record.get(key) != new_record.get(key):
            diffs.append({
                "field": key,
                "old": old_record.get(key),
                "new": new_record.get(key),
                "change_type": "meaningful" if key in MEANINGFUL_FIELDS else "cosmetic_admin"
            })
    return {"diffs": diffs}
```

---

## 22. Additional domain notes for the team

### 22.1 Terminology normalization
The problem statement says many terms refer to the same broad category, including:
- medical benefit drugs
- medical pharmacy drugs
- provider-administered drugs
- physician-administered drugs
- medical injectables
- buy-and-bill drugs.

Similarly, policy documents may be called:
- medical policies
- medical benefit drug policies
- drug and biologic coverage policies
- medical pharmacy policies
- coverage determination guidelines
- clinical policy bulletins.

Your retrieval and parsing code should normalize these aliases.

### 22.2 HCPCS / J-codes
The glossary says HCPCS codes, especially J-codes, are important identifiers for medical-benefit drugs and often appear in policies. They are a useful optional field for cross-payer normalization.

### 22.3 Biosimilars
The Q&A says biosimilars may appear in the same policy as a reference biologic or in separate policies, and may also be referenced through step therapy language. Capture the relationship if convenient, but do not overbuild it for the MVP.

### 22.4 Medical benefit only
Some drugs can appear in both pharmacy and medical benefit contexts, but for this challenge the system should focus on **medical benefit only**. fileciteturn1file2L54-L58

---

## 23. What not to build today

Do not spend time on:
- login/auth
- Medicare or Medicaid
- pharmacy-benefit integration
- full knowledge graph
- broad ingestion across dozens of payers
- production-grade alerting
- elaborate OCR tuning. fileciteturn1file2L54-L58

---

## 24. Definition of done

The MVP is done when:
- a user can select one of 3 to 5 policies,
- ask a drug-specific question,
- see extracted fields,
- see supporting evidence,
- compare the same drug across multiple payers,
- compare two versions of a policy,
- distinguish `No policy found` from `Not covered`,
- export a comparison result.

---

## 25. Final recommendation

The most judge-aligned MVP is:

1. **Ask tab** for daily analyst Q&A
2. **Compare tab** for one-drug cross-payer comparison
3. **Changes tab** for version diff
4. **Evidence tab** for trust and explainability
5. **Export** for workflow realism

That directly matches the pain points, priorities, and judging criteria stated in the Anton Rx problem statement and Q&A.
