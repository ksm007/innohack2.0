# Anton Rx Track — Wireframe Requirements

## Overview

Single-page dark-themed web application. Three-column workspace below a full-width hero header. Target user: market access analyst. Primary interaction is chat-based Q&A with structured side panels for controls and results.

---

## 1. Global Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                          HERO HEADER                                │
│  Left: app name + tagline + description    Right: 3 metric cards    │
└─────────────────────────────────────────────────────────────────────┘
┌───────────────┐  ┌────────────────────────────┐  ┌────────────────┐
│               │  │                            │  │                │
│   CONTROLS    │  │        CHAT PANEL          │  │   INSIGHTS     │
│    PANEL      │  │                            │  │    PANEL       │
│   (320px)     │  │       (fluid, 1.25fr)      │  │   (360px)      │
│               │  │                            │  │                │
└───────────────┘  └────────────────────────────┘  └────────────────┘
```

- Fixed sidebar widths; center column is fluid
- All three columns are independently scrollable
- Collapses to single column below 1180px (chat first, then controls, then insights)

---

## 2. Hero Header

**Left column (wider)**
- Eyebrow label: "Anton Rx's Track" — uppercase mono font, warm amber color
- H1: "Medical Benefit Drug Policy Tracker" — large display font, tight letter spacing
- Subtitle: one-line description of the workspace purpose — muted color

**Right column (narrower)**
- Three metric cards in a vertical stack:
  1. **Policies** — count of loaded documents
  2. **Payers** — count of unique payers in corpus
  3. **Graph** — "Neo4j" or "SQLite" with connection status detail

Each metric card: label (mono uppercase small), large number/value, small detail text below.

---

## 3. Controls Panel (Left Sidebar)

Three stacked sections, each with a section header (eyebrow + h2 + bottom divider line).

### 3.1 Analyst Controls Section
- **Drug input** — text field labeled "Drug", pre-filled with drug name
- **Payer count badge** — pill badge in the section header showing "N payers"
- **Workflow selector** — three vertically stacked selectable cards:
  - Coverage scan
  - Prior auth check
  - Policy change watch
  - Active state: highlighted border + accent background tint
  - Each card: bold title + smaller description text
- **Payer filter** — row of pill toggle buttons (one per payer), wrapping to multiple rows if needed; active = accent tint

### 3.2 Version Pair Section
- **Older version** — dropdown select, full width
- **Newer version** — dropdown select, full width
- **Auto-match card** — info card showing "Auto-matched for [drug]", candidate document count, and helper text

### 3.3 PageIndex Utility Section
- **Background warmup toggle** — pill button toggling "Autobuild on / off"; helper text below explaining the feature
- **Warm PageIndex button** — full-width primary gradient button
- **Index results** (shown after build) — list of compact cards, each: doc ID (truncated with title tooltip) + status pill (success/warning)

**Bottom of panel (conditional):**
- Notice box — blue-tinted with message text
- Error box — red-tinted with error text

---

## 4. Chat Panel (Center, Main)

Three vertical zones: header → composer → thread.

### 4.1 Chat Header
- Eyebrow: "Copilot"
- H2: "Ask the policy tracker"
- Active workflow name shown as a pill badge on the right

### 4.2 Composer Card
- Label: "Question"
- Textarea: 4 rows, full width, resizable vertically
- Actions row below textarea (space-between flex):
  - Left: small helper text "Press Cmd/Ctrl + Enter to run"
  - Right: primary gradient button "Run [Workflow Name]" / "Running..."

### 4.3 Message Thread
- Scrollable container (thin custom scrollbar)
- Messages render top-to-bottom, newest at bottom
- Each message is an article card with:
  - **Meta row**: role name left ("Analyst" or "Anton Copilot"), timestamp right — mono uppercase small
  - **Title** (h3)
  - **Body text** (muted)
  - **User messages**: accent-tinted border and background
  - **Assistant messages**: default card style

**Message content types:**

#### Ask result message
One card per payer record:
- Header row: payer name (h4) + policy name (muted) on left; status pill on right
- Answer text paragraph
- Tag chips row: Coverage · PA · Confidence
- Graph context callout (if present) — left accent border, "Graph context" label
- Evidence list below: each item has page / section / retrieval method as meta tags, then snippet text

#### Compare result message
- Compact 3-column metric grid: Covered count · Prior auth count · Step therapy count
- Graph summary callout (if present)
- Scrollable table:

| Payer | Coverage | Prior Auth | Step Therapy | Site of Care | Effective Date |
|-------|----------|------------|--------------|-------------|----------------|

#### Changes result message
- Summary card: "Change summary" h4 + payer/policy name + "N fields" warning pill + narrative text
- Graph delta card (if present): enabled/fallback status pill + summary + added/removed indications chips
- Diff list — one card per changed field:
  - Field name (h4) + change_type pill
  - Old value (muted)
  - New value

#### System message
- Eyebrow-style header with "Tracker ready" or "Request failed" title
- Body text + optional meta detail line

---

## 5. Insights Panel (Right Sidebar)

Three stacked sections.

### 5.1 Coverage Radar Section
- Empty state: muted placeholder text
- Populated state: 3-column metric grid (Covered / Prior auth / Step therapy counts)
- Graph summary callout below (if compare was run)
- Action row: "Download CSV" (primary) + "Copy Markdown" (secondary ghost) buttons — auto-sized, not stretched

### 5.2 Change Watch Section
- Empty state: muted placeholder text
- Populated state:
  - Info card: "Selected comparison" label, "N fields changed" bold, narrative summary small text
  - Two date chips side by side: "Old: [date]" · "New: [date]"

### 5.3 Tracked Documents Section
- Scrollable list (max 6 items, thin custom scrollbar)
- Each document card:
  - Header row: payer name (h4) + policy name (muted) on left; version label pill on right
  - Tag chips row: document pattern · likely drug

---

## 6. Component Inventory

| Component | Description |
|-----------|-------------|
| `StatusPill` | Inline pill badge. Tones: `success` (green tint), `warning` (amber tint), `neutral` (blue tint) |
| `MetricCard` | Label (mono) + large value + small detail. Used in hero and compare results |
| `WorkflowCard` | Selectable button card with title + description. Active = accent border |
| `Toggle` | Pill button for payer filters and feature toggles. Active = accent tint |
| `EvidenceList` | List of evidence cards: page · section · method meta tags + snippet |
| `InsightCallout` | Card with left accent border (3px). Used for graph context/summary |
| `DiffCard` | Field name + change type pill + old value (muted) + new value |
| `DocumentCard` | Payer/policy card with version pill and tag chips |

---

## 7. Visual Language

- **Theme**: dark, deep navy backgrounds
- **Surface layers**: frosted glass effect (backdrop blur) on all panels
- **Border radius scale**: inputs=12px · chips/pills=999px (full round) · cards=20px · section insets=24px · panels=28px · hero=32px
- **Typography**: IBM Plex Mono for labels/metadata/eyebrows · Sora for headings · IBM Plex Sans for body
- **Accent color**: cyan-blue (#72d5ff) for active states, borders, callout accents
- **Status colors**: green (success/covered) · amber (warning/partial) · red-pink (error)
- **Tag chips**: semi-transparent background + subtle border + pill shape, small mono font
- **Section headers**: eyebrow label above h2, bottom border divider separating header from content
- **Hover states**: cards lift slightly (border brightens, background lightens)
- **Transitions**: 180–200ms ease on background, border-color, transform

---

## 8. States to Show in Wireframe

| State | Location | Notes |
|-------|----------|-------|
| Empty/initial | Chat thread | Single system "Tracker ready" message |
| Loaded corpus | Controls panel | Payer toggles populated, drug pre-filled |
| Workflow selected | Controls panel | One workflow card highlighted |
| Question composing | Composer | Textarea with question text |
| Loading | Run button | "Running..." disabled state |
| Ask result | Chat thread | Per-payer result cards with evidence |
| Compare result | Chat thread + Insights | Table in chat, metrics in insights panel |
| Changes result | Chat thread + Insights | Diff cards in chat, summary in insights panel |
| Index build result | Controls panel | Compact result cards under build button |
| Error | Controls panel bottom | Red error box |
| Notice | Controls panel bottom | Blue notice box |

---

## 9. Responsive Behavior

| Breakpoint | Behavior |
|------------|----------|
| ≥ 1180px | Full 3-column layout |
| < 1180px | Single column: Chat → Controls → Insights (stacked) |
| < 820px | Hero collapses to single column; reduced padding; panels and hero get slightly smaller border radius |
