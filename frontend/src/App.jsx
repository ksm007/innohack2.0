import { useEffect, useMemo, useState } from "react";
import {
  askPolicy,
  buildIndexes,
  clearHistory,
  comparePolicies,
  diffPolicies,
  documentPdfUrl,
  fetchDocuments,
  fetchEvidenceSummary,
  fetchGraphStatus,
  fetchHistory,
  fetchHistoryDetail,
  fetchIndexSettings,
  updateIndexSettings
} from "./api";

const DEFAULT_DRUG = "Infliximab";
const MAX_MESSAGES = 60;

const TRACKER_TABS = [
  { id: "home", label: "Home" },
  { id: "ask", label: "Ask" },
  { id: "compare", label: "Compare" },
  { id: "changes", label: "Changes" },
  { id: "history", label: "History" }
];

const USECASE_SECTIONS = [
  {
    id: "ask",
    title: "Ask Use Cases",
    description: "Single-payer questions with evidence-grounded answers.",
    cases: [
      {
        id: "ask-aetna-ustekinumab",
        label: "Aetna Ustekinumab",
        tab: "ask",
        drugName: "Ustekinumab",
        payerFilters: ["Aetna"],
        question:
          "What prior authorization criteria does this payer require for ustekinumab, and what step therapy alternatives must be tried first?"
      },
      {
        id: "ask-cigna-rituximab",
        label: "Cigna Rituximab",
        tab: "ask",
        drugName: "Rituximab",
        payerFilters: ["Cigna"],
        question: "What prior authorization criteria apply for rituximab for non-oncology indications?"
      },
      {
        id: "ask-emblem-denosumab",
        label: "EmblemHealth Denosumab",
        tab: "ask",
        drugName: "Denosumab",
        payerFilters: ["EmblemHealth"],
        question: "What coverage, authorization, and HCPCS-related guidance does this payer give for denosumab?"
      },
      {
        id: "ask-uhc-botulinum",
        label: "UHC Botulinum Toxins",
        tab: "ask",
        drugName: "Botulinum Toxins",
        payerFilters: ["UnitedHealthcare"],
        question: "What diagnosis-specific criteria and authorization requirements apply to botulinum toxins under this policy?"
      }
    ]
  },
  {
    id: "compare",
    title: "Compare Use Cases",
    description: "Cross-payer comparisons for policy differences and access restrictions.",
    cases: [
      {
        id: "compare-infliximab-medical-benefit",
        label: "Infliximab Medical Benefit",
        tab: "compare",
        drugName: "Infliximab",
        payerFilters: ["Aetna", "Cigna", "UnitedHealthcare"],
        question:
          "How do Aetna, Cigna, and UnitedHealthcare differ in coverage, prior authorization, preferred products, and step therapy for infliximab under the medical benefit?"
      },
      {
        id: "compare-infliximab-biosimilar",
        label: "Infliximab Biosimilar Preference",
        tab: "compare",
        drugName: "Infliximab",
        payerFilters: ["Aetna", "Cigna", "UnitedHealthcare"],
        question:
          "Which infliximab products are preferred or non-preferred across Aetna, Cigna, and UnitedHealthcare, and how does that affect approval?"
      },
      {
        id: "compare-ustekinumab",
        label: "Ustekinumab Payer Compare",
        tab: "compare",
        drugName: "Ustekinumab",
        payerFilters: ["Aetna", "Cigna"],
        question:
          "Compare Aetna and Cigna coverage rules for ustekinumab, including prior authorization and step therapy requirements."
      },
      {
        id: "compare-bevacizumab",
        label: "Bevacizumab Restriction Compare",
        tab: "compare",
        drugName: "Bevacizumab",
        payerFilters: ["Florida Blue", "BCBS NC"],
        question:
          "How do Florida Blue and BCBS NC differ in coverage, prior authorization, and preferred-product restrictions for bevacizumab under the medical benefit?"
      }
    ]
  },
  {
    id: "changes",
    title: "Change Tracking Use Cases",
    description: "Version-to-version review using valid policy pairs present in the corpus.",
    cases: [
      {
        id: "changes-uhc-jan-mar",
        label: "UHC Jan to Mar Bulletin",
        tab: "changes",
        drugName: "Medical Policy Updates",
        payerFilters: ["UnitedHealthcare"],
        oldDocId: "medical-policy-update-bulletin-january-2026-full",
        newDocId: "medical-policy-update-bulletin-march-2026-full",
        question:
          "What changed between the January 2026 and March 2026 UnitedHealthcare medical policy update bulletins, and which changes are meaningful for coverage decisions?"
      },
      {
        id: "changes-uhc-jan-feb",
        label: "UHC Jan to Feb Bulletin",
        tab: "changes",
        drugName: "Medical Policy Updates",
        payerFilters: ["UnitedHealthcare"],
        oldDocId: "medical-policy-update-bulletin-january-2026-full",
        newDocId: "medical-policy-update-bulletin-february-2026-full",
        question:
          "Summarize the meaningful policy changes between the January 2026 and February 2026 UnitedHealthcare medical policy update bulletins."
      },
      {
        id: "changes-uhc-feb-mar",
        label: "UHC Feb to Mar Bulletin",
        tab: "changes",
        drugName: "Medical Policy Updates",
        payerFilters: ["UnitedHealthcare"],
        oldDocId: "medical-policy-update-bulletin-february-2026-full",
        newDocId: "medical-policy-update-bulletin-march-2026-full",
        question:
          "What changed between the February 2026 and March 2026 UnitedHealthcare medical policy update bulletins?"
      }
    ]
  }
];

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function groupPayers(documents) {
  return [...new Set(documents.map((doc) => doc.payer))].filter(Boolean).sort();
}

function formatList(items) {
  return items?.filter(Boolean).join(", ") || "none";
}

function createMessage(role, kind, payload = {}) {
  return {
    id: `${role}-${kind}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    kind,
    timestamp: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
    ...payload
  };
}

function buildCompareHighlights(rows = []) {
  if (!rows.length) return [];
  return [
    {
      label: "Covered",
      value: rows.filter((row) => normalizeText(row.coverage).includes("covered")).length,
      detail: `${rows.length} payer rows`
    },
    {
      label: "Prior auth",
      value: rows.filter((row) => normalizeText(row.prior_auth).startsWith("yes")).length,
      detail: "policies requiring PA"
    },
    {
      label: "Step therapy",
      value: rows.filter((row) => normalizeText(row.step_therapy).startsWith("yes")).length,
      detail: "policies with step edits"
    }
  ];
}

function pickVersionPair(documents, drugName, preferredPayer = "") {
  const lowered = normalizeText(drugName);
  const preferred = normalizeText(preferredPayer);
  const candidates = documents.filter((doc) => {
    const policy = normalizeText(doc.policy_name);
    const likely = normalizeText(doc.likely_drug);
    const payer = normalizeText(doc.payer);
    const matchesDrug = lowered && (policy.includes(lowered) || likely.includes(lowered));
    const matchesPayer = !preferred || payer.includes(preferred);
    return matchesDrug && matchesPayer;
  });

  const grouped = new Map();
  for (const doc of candidates) {
    if (!doc.version_group) continue;
    const group = grouped.get(doc.version_group) || [];
    group.push(doc);
    grouped.set(doc.version_group, group);
  }

  const viable = [...grouped.values()]
    .filter((items) => items.length >= 2)
    .sort((left, right) => right.length - left.length);

  if (!viable.length) return null;
  const group = viable[0]
    .slice()
    .sort((left, right) => normalizeText(left.version_label).localeCompare(normalizeText(right.version_label)));

  return {
    oldDocId: group[0].doc_id,
    newDocId: group[group.length - 1].doc_id
  };
}

function buildLooseChangeGroupKey(doc) {
  return `${doc.payer} ${doc.policy_name}`
    .toLowerCase()
    .replace(/\b(january|february|march|april|may|june|july|august|september|october|november|december)\b/g, "")
    .replace(/\b(20\d{2}|\d{8})\b/g, "")
    .replace(/\b(full|current)\b/g, "")
    .replace(/[\W_]+/g, " ")
    .trim();
}

function deriveValidChangePairs(documents) {
  const grouped = new Map();
  for (const doc of documents) {
    const key = doc.version_group || buildLooseChangeGroupKey(doc);
    if (!key) continue;
    const items = grouped.get(key) || [];
    items.push(doc);
    grouped.set(key, items);
  }

  return [...grouped.entries()]
    .filter(([, items]) => items.length >= 2)
    .map(([pairId, items]) => {
      const ordered = items
        .slice()
        .sort((left, right) =>
          `${left.version_label} ${left.policy_name}`.localeCompare(`${right.version_label} ${right.policy_name}`)
        );
      const first = ordered[0];
      const last = ordered[ordered.length - 1];
      return {
        pairId,
        title: `${first.payer} · ${first.policy_name}`,
        oldDocId: first.doc_id,
        newDocId: last.doc_id,
        oldLabel: first.policy_name,
        newLabel: last.policy_name,
        payer: first.payer,
        drugName: first.likely_drug || first.policy_name,
      };
    })
    .sort((left, right) => left.title.localeCompare(right.title));
}

function getDocumentLabel(documents, docId) {
  return documents.find((doc) => doc.doc_id === docId)?.policy_name || "Unknown document";
}

function statusTone(status = "") {
  const normalized = normalizeText(status);
  if (normalized === "answered" || normalized === "complete") return "success";
  if (normalized === "review required" || normalized === "partial") return "warning";
  return "neutral";
}

function humanizeFieldLabel(field) {
  return field.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function compactValue(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join(", ") || "none";
  return String(value || "unknown");
}

function buildReadableAskSummary(record) {
  const parts = [];
  parts.push(`Coverage is ${record.coverage_status}.`);
  if (record.prior_auth_required !== "unknown") {
    parts.push(`Prior authorization is ${record.prior_auth_required}.`);
  }
  if (record.step_therapy !== "unknown") {
    parts.push(`Step therapy is noted.`);
  }
  if (record.site_of_care !== "unknown") {
    parts.push(`Site of care guidance is present.`);
  }
  if (record.effective_date !== "unknown" && record.effective_date !== "not stated in snippets") {
    parts.push(`Effective date: ${record.effective_date}.`);
  }
  return parts.join(" ");
}

function buildAskHighlights(record) {
  const highlights = [];
  if (record.coverage_status !== "unknown") {
    highlights.push(`Coverage: ${record.coverage_status}`);
  }
  if (record.prior_auth_required !== "unknown") {
    highlights.push(`Prior auth: ${record.prior_auth_required}`);
  }
  if (record.step_therapy !== "unknown") {
    highlights.push(`Step therapy: ${record.step_therapy}`);
  }
  if (record.site_of_care !== "unknown") {
    highlights.push(`Site of care: ${record.site_of_care}`);
  }
  if (record.covered_indications?.length) {
    highlights.push(`Covered indications: ${record.covered_indications.slice(0, 4).join(", ")}`);
  }
  return highlights.slice(0, 4);
}

function extractHistoryExplanation(detail) {
  const payload = detail?.response_payload || {};
  if (detail.kind === "ask") {
    const records = payload.records || [];
    if (!records.length) return detail.summary;
    return `Returned ${records.length} payer records. ${records[0].payer}: ${buildReadableAskSummary(records[0])}`;
  }
  if (detail.kind === "compare") {
    const rows = payload.rows || [];
    if (!rows.length) return detail.summary;
    return `Compared ${rows.length} payer rows. ${rows.map((row) => `${row.payer}: ${row.coverage}`).join(" | ")}`;
  }
  if (detail.kind === "changes") {
    return payload.narrative_summary || detail.summary;
  }
  return detail.summary;
}

function Icon({ name }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.75",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  };
  const map = {
    home: (
      <svg {...common}>
        <path d="M3 10.5 12 3l9 7.5" />
        <path d="M5 9.5V21h14V9.5" />
      </svg>
    ),
    ask: (
      <svg {...common}>
        <path d="M12 18h.01" />
        <path d="M9.09 9a3 3 0 1 1 5.82 1c0 2-3 3-3 3" />
        <circle cx="12" cy="12" r="9" />
      </svg>
    ),
    compare: (
      <svg {...common}>
        <path d="M7 4v16" />
        <path d="M17 4v16" />
        <path d="M7 8h10" />
        <path d="M7 16h10" />
      </svg>
    ),
    changes: (
      <svg {...common}>
        <path d="M3 12a9 9 0 0 1 15.5-6.2L21 8" />
        <path d="M21 3v5h-5" />
        <path d="M21 12a9 9 0 0 1-15.5 6.2L3 16" />
        <path d="M3 21v-5h5" />
      </svg>
    ),
    history: (
      <svg {...common}>
        <path d="M12 8v5l3 2" />
        <path d="M3.05 11A9 9 0 1 1 6 18.3" />
        <path d="M3 4v7h7" />
      </svg>
    ),
    search: (
      <svg {...common}>
        <circle cx="11" cy="11" r="6" />
        <path d="m20 20-3.5-3.5" />
      </svg>
    ),
    launch: (
      <svg {...common}>
        <path d="m22 2-7 20-4-9-9-4 20-7Z" />
        <path d="M22 2 11 13" />
      </svg>
    ),
    file: (
      <svg {...common}>
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
      </svg>
    ),
    chevron: (
      <svg {...common}>
        <path d="m6 9 6 6 6-6" />
      </svg>
    )
  };
  return map[name] || null;
}

function StatusPill({ tone = "neutral", children }) {
  return <span className={`status-pill ${tone}`}>{children}</span>;
}

function MetricTile({ label, value, detail }) {
  return (
    <article className="metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function SpinnerLabel({ text }) {
  return (
    <span className="spinner-label">
      <span className="spinner-dot" />
      <span>{text}</span>
    </span>
  );
}

function EvidenceCard({ docId, evidence, question }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState("");
  const [sourceMethod, setSourceMethod] = useState("");
  const [error, setError] = useState("");

  async function handleToggle() {
    const next = !open;
    setOpen(next);
    if (!next || summary || loading) return;
    setLoading(true);
    setError("");
    try {
      const result = await fetchEvidenceSummary({
        doc_id: docId,
        page: evidence.page,
        section: evidence.section,
        snippet: evidence.snippet,
        question
      });
      setSummary(result.summary);
      setSourceMethod(result.source_method);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <article className="evidence-card">
      <div className="evidence-meta">
        <span>Page {evidence.page}</span>
        <span>{evidence.section}</span>
        <span>{evidence.retrieval_method}</span>
      </div>
      <p>{evidence.snippet}</p>
      <div className="evidence-actions">
        <a href={documentPdfUrl(docId, evidence.page)} target="_blank" rel="noreferrer" className="link-button">
          <Icon name="file" />
          <span>Open PDF page</span>
        </a>
        <button type="button" className="ghost-button" onClick={handleToggle}>
          <span>{open ? "Hide page summary" : "Show page summary"}</span>
          <Icon name="chevron" />
        </button>
      </div>
      {open ? (
        <div className="dropdown-panel">
          {loading ? <SpinnerLabel text="Generating page summary..." /> : null}
          {error ? <p className="error-inline">{error}</p> : null}
          {!loading && !error && summary ? (
            <>
              <p>{summary}</p>
              <small>{sourceMethod === "openai" ? "Generated with OpenAI" : "Fallback summary"}</small>
            </>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function EvidenceList({ docId, evidence, question }) {
  if (!evidence?.length) return <p className="muted">No evidence snippets returned.</p>;
  return (
    <div className="evidence-list">
      {evidence.map((item, index) => (
        <EvidenceCard key={`${item.page}-${index}`} docId={docId} evidence={item} question={question} />
      ))}
    </div>
  );
}

function AskRecordCard({ record, question }) {
  const highlights = buildAskHighlights(record);
  return (
    <article className="result-card">
      <div className="result-head">
        <div>
          <h4>{record.payer}</h4>
          <p className="muted">{record.policy_name}</p>
        </div>
        <StatusPill tone={statusTone(record.status)}>{record.status}</StatusPill>
      </div>

      <div className="summary-band">
        <strong>Readable summary</strong>
        <p>{buildReadableAskSummary(record)}</p>
      </div>

      <div className="highlight-list">
        {highlights.map((item) => (
          <div key={item} className="highlight-item">
            {item}
          </div>
        ))}
      </div>

      <details className="details-block">
        <summary>Detailed explanation</summary>
        <div className="details-grid">
          <p><strong>Answer:</strong> {record.answer}</p>
          <p><strong>Prior auth criteria:</strong> {compactValue(record.prior_auth_criteria)}</p>
          <p><strong>Covered indications:</strong> {compactValue(record.covered_indications)}</p>
          <p><strong>Biosimilars:</strong> {compactValue(record.biosimilar_reference_relationships)}</p>
          <p><strong>Effective date:</strong> {record.effective_date}</p>
          <p><strong>Site of care:</strong> {record.site_of_care}</p>
        </div>
      </details>

      {record.graph_context ? (
        <div className="insight-callout">
          <strong>Graph context</strong>
          <p className="muted">{record.graph_context.status_message}</p>
          <p className="muted">Known payers: {formatList(record.graph_context.known_payers_for_drug)}</p>
          <p className="muted">Known versions: {formatList(record.graph_context.known_versions_for_policy)}</p>
        </div>
      ) : null}

      <EvidenceList docId={record.doc_id} evidence={record.evidence} question={question} />
    </article>
  );
}

function AskPreview({ records, question }) {
  return (
    <div className="message-stack">
      {records.map((record) => (
        <AskRecordCard key={record.doc_id} record={record} question={question} />
      ))}
    </div>
  );
}

function ComparePreview({ rows, graphSummary }) {
  const highlights = buildCompareHighlights(rows);
  return (
    <div className="message-stack">
      <div className="metric-grid compact">
        {highlights.map((item) => (
          <MetricTile key={item.label} {...item} />
        ))}
      </div>
      {graphSummary ? (
        <div className="insight-callout">
          <strong>Graph summary</strong>
          <p className="muted">{graphSummary.status_message}</p>
          <p className="muted">Payers: {formatList(graphSummary.payer_names)}</p>
        </div>
      ) : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Payer</th>
              <th>Coverage</th>
              <th>Prior Auth</th>
              <th>Step Therapy</th>
              <th>Site of Care</th>
              <th>Effective Date</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.payer}-${row.policy_name}`}>
                <td>{row.payer}</td>
                <td>{row.coverage}</td>
                <td>{row.prior_auth}</td>
                <td>{row.step_therapy}</td>
                <td>{row.site_of_care}</td>
                <td>{row.effective_date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ChangesPreview({ changeResult }) {
  return (
    <div className="message-stack">
      <article className="result-card">
        <div className="result-head">
          <div>
            <h4>Change summary</h4>
            <p className="muted">
              {changeResult.old_record.payer} · {changeResult.old_record.policy_name}
            </p>
          </div>
          <StatusPill tone="warning">{changeResult.diffs.length} fields</StatusPill>
        </div>
        <div className="summary-band">
          <strong>Readable summary</strong>
          <p>{changeResult.narrative_summary}</p>
        </div>

        <details className="details-block">
          <summary>Detailed explanation</summary>
          <div className="details-grid">
            {changeResult.diffs.map((diff) => (
              <div key={diff.field} className="change-line">
                <strong>{humanizeFieldLabel(diff.field)}:</strong> {compactValue(diff.old_value)} → {compactValue(diff.new_value)}
              </div>
            ))}
          </div>
        </details>
      </article>

      {changeResult.graph_summary ? (
        <article className="result-card">
          <div className="result-head">
            <h4>Graph delta</h4>
            <StatusPill tone={changeResult.graph_summary.enabled ? "success" : "neutral"}>
              {changeResult.graph_summary.enabled ? "neo4j" : "fallback"}
            </StatusPill>
          </div>
          <p>{changeResult.graph_summary.summary}</p>
        </article>
      ) : null}
    </div>
  );
}

function MessageBubble({ message }) {
  return (
    <article className={`message-bubble ${message.role}`}>
      <div className="message-meta">
        <span>{message.role === "user" ? "Analyst" : "Anton Copilot"}</span>
        <span>{message.timestamp}</span>
      </div>
      {message.title ? <h3>{message.title}</h3> : null}
      {message.text ? <p>{message.text}</p> : null}
      {message.kind === "ask" ? <AskPreview records={message.records} question={message.question} /> : null}
      {message.kind === "compare" ? <ComparePreview rows={message.rows} graphSummary={message.graphSummary} /> : null}
      {message.kind === "changes" ? <ChangesPreview changeResult={message.changeResult} /> : null}
      {message.kind === "system" && message.meta ? <p className="muted">{message.meta}</p> : null}
    </article>
  );
}

function HistoryCard({ entry, detail, loading, onToggle }) {
  return (
    <article className="history-card">
      <div className="result-head">
        <div>
          <h3>{entry.title}</h3>
          <p className="muted">
            {entry.kind} · {new Date(entry.created_at).toLocaleString()}
          </p>
        </div>
        <StatusPill tone={statusTone(entry.status)}>{entry.kind}</StatusPill>
      </div>

      <div className="summary-band">
        <strong>Summary</strong>
        <p>{detail ? extractHistoryExplanation(detail) : entry.summary}</p>
      </div>

      <div className="tag-row">
        <span>Drug: {entry.drug_name || "unknown"}</span>
        <span>Payers: {formatList(entry.payer_filters || [])}</span>
      </div>

      <button type="button" className="ghost-button history-toggle" onClick={onToggle}>
        <span>{detail ? "Hide details" : "Show details"}</span>
        <Icon name="chevron" />
      </button>

      {loading ? <SpinnerLabel text="Loading saved details..." /> : null}
      {detail ? (
        <div className="dropdown-panel">
          {detail.kind === "ask" ? (
            <AskPreview records={detail.response_payload.records || []} question={detail.question} />
          ) : null}
          {detail.kind === "compare" ? (
            <ComparePreview
              rows={detail.response_payload.rows || []}
              graphSummary={detail.response_payload.graph_summary || null}
            />
          ) : null}
          {detail.kind === "changes" ? (
            <ChangesPreview changeResult={detail.response_payload} />
          ) : null}

          <details className="details-block">
            <summary>Request and response payload</summary>
            <div className="payload-grid">
              <div>
                <strong>Request</strong>
                <pre>{JSON.stringify(detail.request_payload, null, 2)}</pre>
              </div>
              <div>
                <strong>Response</strong>
                <pre>{JSON.stringify(detail.response_payload, null, 2)}</pre>
              </div>
            </div>
          </details>
        </div>
      ) : null}
    </article>
  );
}

export default function App() {
  const [documents, setDocuments] = useState([]);
  const [graphStatus, setGraphStatus] = useState(null);
  const [indexSettings, setIndexSettings] = useState(null);
  const [historyEntries, setHistoryEntries] = useState([]);
  const [historyDetails, setHistoryDetails] = useState({});
  const [historyLoading, setHistoryLoading] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeTab, setActiveTab] = useState("home");
  const [activeUseCaseId, setActiveUseCaseId] = useState("");
  const [drugName, setDrugName] = useState(DEFAULT_DRUG);
  const [question, setQuestion] = useState(USECASE_SECTIONS[1].cases[0].question);
  const [selectedPayers, setSelectedPayers] = useState(["Aetna", "Cigna", "UnitedHealthcare"]);
  const [oldDocId, setOldDocId] = useState("");
  const [newDocId, setNewDocId] = useState("");
  const [compareResult, setCompareResult] = useState(null);
  const [askResult, setAskResult] = useState(null);
  const [changeResult, setChangeResult] = useState(null);
  const [indexResult, setIndexResult] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isIndexing, setIsIndexing] = useState(false);
  const [isUpdatingIndexSettings, setIsUpdatingIndexSettings] = useState(false);

  const payers = useMemo(() => groupPayers(documents), [documents]);
  const validChangePairs = useMemo(() => deriveValidChangePairs(documents), [documents]);
  const compareHighlights = useMemo(
    () => buildCompareHighlights(compareResult?.rows || []),
    [compareResult]
  );
  const recentHistory = useMemo(() => historyEntries.slice(0, 12), [historyEntries]);
  const matchingDocuments = useMemo(() => {
    const lowered = normalizeText(drugName);
    if (!lowered) return documents;
    return documents.filter((doc) => {
      const policy = normalizeText(doc.policy_name);
      const likely = normalizeText(doc.likely_drug);
      return policy.includes(lowered) || likely.includes(lowered);
    });
  }, [documents, drugName]);

  useEffect(() => {
    async function load() {
      try {
        const [docs, graph, indexConfig, history] = await Promise.all([
          fetchDocuments(),
          fetchGraphStatus(),
          fetchIndexSettings(),
          fetchHistory()
        ]);
        const defaultPair = deriveValidChangePairs(docs)[0] || pickVersionPair(docs, DEFAULT_DRUG, "UnitedHealthcare");
        const defaultPayers = ["Aetna", "Cigna", "UnitedHealthcare"].filter((payer) => groupPayers(docs).includes(payer));

        setDocuments(docs);
        setGraphStatus(graph);
        setIndexSettings(indexConfig);
        setHistoryEntries(history);
        setSelectedPayers(defaultPayers.length ? defaultPayers : groupPayers(docs).slice(0, 3));
        if (defaultPair) {
          setOldDocId(defaultPair.oldDocId);
          setNewDocId(defaultPair.newDocId);
        } else if (docs.length >= 2) {
          setOldDocId(docs[0].doc_id);
          setNewDocId(docs[1].doc_id);
        }
        setMessages([
          createMessage("assistant", "system", {
            title: "Workspace ready",
            text: "Use the grouped use cases to open the right tracker and type naturally. Evidence cards now link back to the source PDF page and can generate page summaries.",
            meta: `${docs.length} documents loaded across ${groupPayers(docs).length} payers.`
          })
        ]);
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (!documents.length) return;
    const pair = pickVersionPair(documents, drugName, selectedPayers[0]) || validChangePairs[0];
    if (pair) {
      setOldDocId(pair.oldDocId);
      setNewDocId(pair.newDocId);
    }
  }, [documents, drugName, selectedPayers, validChangePairs]);

  function appendMessage(msg) {
    setMessages((current) => [...current, msg].slice(-MAX_MESSAGES));
  }

  async function refreshHistory() {
    try {
      const history = await fetchHistory();
      setHistoryEntries(history);
    } catch {
      // keep UI usable
    }
  }

  async function handleClearHistory() {
    setError("");
    setNotice("");
    try {
      const result = await clearHistory();
      setHistoryEntries([]);
      setHistoryDetails({});
      setNotice(result.message || "History cleared.");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  function togglePayer(payer) {
    setSelectedPayers((current) =>
      current.includes(payer) ? current.filter((value) => value !== payer) : [...current, payer]
    );
  }

  function loadUseCase(useCase) {
    setActiveUseCaseId(useCase.id);
    setActiveTab(useCase.tab);
    setDrugName(useCase.drugName);
    setQuestion(useCase.question);
    setSelectedPayers(useCase.payerFilters || []);

    if (useCase.tab === "changes") {
      const explicitPair = useCase.oldDocId && useCase.newDocId
        ? { oldDocId: useCase.oldDocId, newDocId: useCase.newDocId }
        : validChangePairs[0];
      if (explicitPair) {
        setOldDocId(explicitPair.oldDocId);
        setNewDocId(explicitPair.newDocId);
      }
    }

    setNotice(`Loaded ${useCase.label}. Review the prompt, adjust if needed, and run it manually from the ${useCase.tab} tracker.`);
    setError("");
  }

  async function executeAsk(nextDrugName, nextQuestion, nextPayers, title = "Ask tracker") {
    const result = await askPolicy({
      drug_name: nextDrugName,
      question: nextQuestion,
      payer_filters: nextPayers
    });
    setAskResult(result);
    appendMessage(
      createMessage("assistant", "ask", {
        title,
        text: `Reviewed ${result.records.length} payer policies for ${nextDrugName}.`,
        question: nextQuestion,
        records: result.records
      })
    );
  }

  async function executeCompare(nextDrugName, nextQuestion, nextPayers, title = "Compare tracker") {
    const result = await comparePolicies({
      drug_name: nextDrugName,
      question: nextQuestion,
      payer_filters: nextPayers
    });
    setCompareResult(result);
    appendMessage(
      createMessage("assistant", "compare", {
        title,
        text: `Compared ${result.rows.length} normalized payer rows for ${nextDrugName}.`,
        rows: result.rows,
        graphSummary: result.graph_summary || null
      })
    );
  }

  async function executeChanges(nextDrugName, nextQuestion, nextOldDocId, nextNewDocId, title = "Change tracker") {
    const result = await diffPolicies({
      drug_name: nextDrugName,
      old_doc_id: nextOldDocId,
      new_doc_id: nextNewDocId,
      question: nextQuestion
    });
    setChangeResult(result);
    appendMessage(
      createMessage("assistant", "changes", {
        title,
        text: `Compared ${getDocumentLabel(documents, nextOldDocId)} against ${getDocumentLabel(documents, nextNewDocId)}.`,
        changeResult: result
      })
    );
  }

  async function runCurrentTab() {
    if (!question.trim()) return;
    setError("");
    setNotice("");
    setIsSubmitting(true);
    appendMessage(createMessage("user", "text", { title: `${activeTab} tracker`, text: question.trim() }));

    try {
      if (activeTab === "ask") {
        await executeAsk(drugName, question, selectedPayers, "Ask tracker");
      } else if (activeTab === "compare") {
        await executeCompare(drugName, question, selectedPayers, "Compare tracker");
      } else if (activeTab === "changes") {
        await executeChanges(drugName, question, oldDocId, newDocId, "Change tracker");
      }
      await refreshHistory();
    } catch (requestError) {
      setError(requestError.message);
      appendMessage(createMessage("assistant", "system", { title: "Request failed", text: requestError.message }));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleToggleIndexWarmup() {
    if (!indexSettings) return;
    setIsUpdatingIndexSettings(true);
    setError("");
    setNotice("");
    try {
      const next = await updateIndexSettings({ enabled: !indexSettings.enabled });
      setIndexSettings(next);
      setNotice(next.detail);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsUpdatingIndexSettings(false);
    }
  }

  async function handleBuildIndexes() {
    setIsIndexing(true);
    setError("");
    setNotice("");
    try {
      const targetIds = matchingDocuments.length
        ? matchingDocuments.map((doc) => doc.doc_id)
        : documents.map((doc) => doc.doc_id);
      const result = await buildIndexes({ doc_ids: targetIds, force: false });
      setIndexResult(result);
      const counts = result.results.reduce((acc, item) => {
        acc[item.status] = (acc[item.status] || 0) + 1;
        return acc;
      }, {});
      setNotice(
        `PageIndex warmup finished for ${targetIds.length} docs. Cached: ${counts.cached || 0}, completed: ${counts.completed || 0}, failed: ${counts.failed || 0}.`
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsIndexing(false);
    }
  }

  async function toggleHistoryDetails(entryId) {
    if (historyDetails[entryId]) {
      setHistoryDetails((current) => {
        const next = { ...current };
        delete next[entryId];
        return next;
      });
      return;
    }

    setHistoryLoading((current) => ({ ...current, [entryId]: true }));
    try {
      const detail = await fetchHistoryDetail(entryId);
      setHistoryDetails((current) => ({ ...current, [entryId]: detail }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setHistoryLoading((current) => ({ ...current, [entryId]: false }));
    }
  }

  function downloadCompareCsv() {
    if (!compareResult?.rows?.length) return;
    const headers = ["Payer", "Policy", "Drug", "Coverage", "Prior Auth", "Step Therapy", "Site of Care", "Effective Date", "Status"];
    const lines = [
      headers.join(","),
      ...compareResult.rows.map((row) =>
        [
          row.payer,
          row.policy_name,
          row.drug,
          row.coverage,
          row.prior_auth,
          row.step_therapy,
          row.site_of_care,
          row.effective_date,
          row.status
        ]
          .map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`)
          .join(",")
      )
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${drugName.toLowerCase().replaceAll(/\s+/g, "_")}_compare.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 100);
  }

  if (loading) {
    return <div className="loading-screen">Loading Anton Rx Track...</div>;
  }

  return (
    <div className="tracker-app">
      <header className="topbar">
        <div className="brand">Anton Rx Track</div>
        <nav className="topnav" aria-label="Tracker tabs">
          {TRACKER_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? "topnav-item active" : "topnav-item"}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon name={tab.id} />
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>
        <label className="search-box">
          <Icon name="search" />
          <input
            value={drugName}
            onChange={(event) => setDrugName(event.target.value)}
            placeholder="Search drug name..."
          />
        </label>
      </header>

      <div className="shell">
        <aside className="sidebar">
          <section className="sidebar-card">
            <span className="eyebrow">Current focus</span>
            <h2>{activeTab === "home" ? "Use case library" : `${activeTab[0].toUpperCase()}${activeTab.slice(1)} tracker`}</h2>
            <p className="muted">
              {activeTab === "home"
                ? "Pick a use case, then move to the corresponding tracker and type naturally."
                : "Review or edit the prefilled prompt, then run the selected tracker manually."}
            </p>
          </section>

          <section className="sidebar-card">
            <span className="eyebrow">Drug</span>
            <input value={drugName} onChange={(event) => setDrugName(event.target.value)} />
          </section>

          <section className="sidebar-card">
            <span className="eyebrow">Payers</span>
            <div className="payer-list">
              {payers.map((payer) => (
                <label key={payer} className="payer-row">
                  <input
                    type="checkbox"
                    checked={selectedPayers.includes(payer)}
                    onChange={() => togglePayer(payer)}
                  />
                  <span>{payer}</span>
                </label>
              ))}
            </div>
          </section>

          <section className="sidebar-card">
            <span className="eyebrow">Indexing</span>
            <button
              type="button"
              className={indexSettings?.enabled ? "soft-button active" : "soft-button"}
              onClick={handleToggleIndexWarmup}
              disabled={isUpdatingIndexSettings}
            >
              {isUpdatingIndexSettings ? "Updating..." : indexSettings?.enabled ? "Autobuild on" : "Autobuild off"}
            </button>
            <button type="button" className="soft-button" onClick={handleBuildIndexes} disabled={isIndexing}>
              {isIndexing ? "Warming indexes..." : "Warm current corpus"}
            </button>
            {indexResult ? <small className="muted">{indexResult.results.length} index actions recorded.</small> : null}
          </section>

          {notice ? <div className="notice-box">{notice}</div> : null}
          {error ? <div className="error-box">{error}</div> : null}
        </aside>

        <main className="content">
          {activeTab === "home" ? (
            <>
              <section className="hero">
                <div className="hero-copy">
                  <span className="eyebrow">Hero</span>
                  <h1>Choose a use case, then type naturally</h1>
                  <p>
                    The home screen is now a guided use-case library. Each card loads the right tracker, drug, payer set, and starter query, but nothing auto-runs.
                  </p>
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => loadUseCase(USECASE_SECTIONS[1].cases[0])}
                  >
                    <Icon name="launch" />
                    <span>Open Recommended Compare Use Case</span>
                  </button>
                </div>
                <div className="hero-metrics">
                  <MetricTile label="Policies" value={documents.length} detail="documents discovered" />
                  <MetricTile label="Payers" value={payers.length} detail="active in corpus" />
                  <MetricTile
                    label="History"
                    value={historyEntries.length}
                    detail="saved backend runs"
                  />
                </div>
              </section>

              {USECASE_SECTIONS.map((section) => (
                <section key={section.id} className="usecase-section">
                  <div className="section-header">
                    <div>
                      <span className="eyebrow">{section.id}</span>
                      <h2>{section.title}</h2>
                      <p className="muted">{section.description}</p>
                    </div>
                    <StatusPill tone="neutral">{section.cases.length} use cases</StatusPill>
                  </div>

                  <div className="usecase-grid">
                    {section.cases.map((useCase) => (
                      <article
                        key={useCase.id}
                        className={activeUseCaseId === useCase.id ? "usecase-card active" : "usecase-card"}
                      >
                        <div className="result-head">
                          <div>
                            <h3>{useCase.label}</h3>
                            <p className="muted">{useCase.drugName}</p>
                          </div>
                          <StatusPill tone="neutral">{useCase.tab}</StatusPill>
                        </div>
                        <p>{useCase.question}</p>
                        <div className="tag-row">
                          <span>Payers: {formatList(useCase.payerFilters)}</span>
                          {useCase.oldDocId ? <span>Version-aware</span> : null}
                        </div>
                        <button type="button" className="soft-button" onClick={() => loadUseCase(useCase)}>
                          Open in {useCase.tab}
                        </button>
                      </article>
                    ))}
                  </div>
                </section>
              ))}
            </>
          ) : null}

          {["ask", "compare", "changes"].includes(activeTab) ? (
            <>
              <section className="tracker-header">
                <div>
                  <span className="eyebrow">Tracker</span>
                  <h1>
                    {activeTab === "ask" && "Ask tracker"}
                    {activeTab === "compare" && "Compare tracker"}
                    {activeTab === "changes" && "Change tracker"}
                  </h1>
                  <p>
                    {activeTab === "ask" && "Readable summaries first, detailed extraction second, evidence pages linked back to source PDFs."}
                    {activeTab === "compare" && "Compare normalized payer rows and export the output when needed."}
                    {activeTab === "changes" && "Use detected valid pairs or choose explicit documents for version review."}
                  </p>
                </div>
              </section>

              <section className="composer-card">
                <label className="field">
                  <span>Question</span>
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    rows={4}
                    onKeyDown={(event) => {
                      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                        event.preventDefault();
                        runCurrentTab();
                      }
                    }}
                  />
                </label>

                {activeTab === "changes" ? (
                  <>
                    <label className="field">
                      <span>Detected valid pairs</span>
                      <select
                        value={validChangePairs.find((pair) => pair.oldDocId === oldDocId && pair.newDocId === newDocId)?.pairId || ""}
                        onChange={(event) => {
                          const selected = validChangePairs.find((pair) => pair.pairId === event.target.value);
                          if (!selected) return;
                          setOldDocId(selected.oldDocId);
                          setNewDocId(selected.newDocId);
                          setDrugName(selected.drugName);
                        }}
                      >
                        {validChangePairs.length ? (
                          validChangePairs.map((pair) => (
                            <option key={pair.pairId} value={pair.pairId}>
                              {pair.oldLabel} → {pair.newLabel}
                            </option>
                          ))
                        ) : (
                          <option value="">No valid version pairs found</option>
                        )}
                      </select>
                    </label>

                    <div className="version-pair">
                      <label className="field">
                        <span>Older version</span>
                        <select value={oldDocId} onChange={(event) => setOldDocId(event.target.value)}>
                          {documents.map((doc) => (
                            <option key={doc.doc_id} value={doc.doc_id}>
                              {doc.policy_name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field">
                        <span>Newer version</span>
                        <select value={newDocId} onChange={(event) => setNewDocId(event.target.value)}>
                          {documents.map((doc) => (
                            <option key={doc.doc_id} value={doc.doc_id}>
                              {doc.policy_name}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  </>
                ) : null}

                <div className="composer-actions">
                  <span className="muted">Press Cmd/Ctrl + Enter to run this tracker.</span>
                  <button type="button" className="primary-button" onClick={runCurrentTab} disabled={isSubmitting}>
                    <Icon name="launch" />
                    <span>{isSubmitting ? "Running..." : `Run ${activeTab}`}</span>
                  </button>
                </div>
              </section>

              <section className="tracker-grid">
                <div className="thread-panel">
                  {messages.map((message) => (
                    <MessageBubble key={message.id} message={message} />
                  ))}
                </div>

                <aside className="insight-panel">
                  {activeTab === "compare" ? (
                    <article className="panel-card">
                      <div className="result-head">
                        <h3>Compare signals</h3>
                        <StatusPill tone="neutral">{compareResult?.rows?.length || 0} rows</StatusPill>
                      </div>
                      {compareHighlights.length ? (
                        <div className="metric-grid compact">
                          {compareHighlights.map((item) => (
                            <MetricTile key={item.label} {...item} />
                          ))}
                        </div>
                      ) : (
                        <p className="muted">Run compare to populate payer metrics.</p>
                      )}
                      {compareResult?.rows?.length ? (
                        <button type="button" className="soft-button" onClick={downloadCompareCsv}>
                          Download CSV
                        </button>
                      ) : null}
                    </article>
                  ) : null}

                  {activeTab === "ask" && askResult?.records?.length ? (
                    <article className="panel-card">
                      <div className="result-head">
                        <h3>Ask summary</h3>
                        <StatusPill tone="success">{askResult.records.length} records</StatusPill>
                      </div>
                      <p>{buildReadableAskSummary(askResult.records[0])}</p>
                    </article>
                  ) : null}

                  {activeTab === "changes" ? (
                    <article className="panel-card">
                      <div className="result-head">
                        <h3>Available change pairs</h3>
                        <StatusPill tone="neutral">{validChangePairs.length}</StatusPill>
                      </div>
                      {validChangePairs.length ? (
                        <div className="mini-list">
                          {validChangePairs.slice(0, 6).map((pair) => (
                            <div key={pair.pairId} className="mini-list-item">
                              <strong>{pair.payer}</strong>
                              <span>{pair.oldLabel} → {pair.newLabel}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="muted">No valid version pairs detected in the current corpus.</p>
                      )}
                    </article>
                  ) : null}

                  <article className="panel-card">
                    <div className="result-head">
                      <h3>Relevant documents</h3>
                      <StatusPill tone="neutral">{matchingDocuments.length || documents.length}</StatusPill>
                    </div>
                    <div className="document-list">
                      {(matchingDocuments.length ? matchingDocuments : documents).slice(0, 6).map((doc) => (
                        <article key={doc.doc_id} className="document-card">
                          <div className="result-head">
                            <div>
                              <h4>{doc.payer}</h4>
                              <p className="muted">{doc.policy_name}</p>
                            </div>
                            <StatusPill tone="neutral">{doc.version_label || "current"}</StatusPill>
                          </div>
                          <div className="tag-row">
                            <span>{doc.document_pattern}</span>
                            <span>{doc.likely_drug || "multi-drug"}</span>
                          </div>
                        </article>
                      ))}
                    </div>
                  </article>
                </aside>
              </section>
            </>
          ) : null}

          {activeTab === "history" ? (
            <section className="history-panel">
              <div className="section-header">
                <div>
                  <span className="eyebrow">History</span>
                  <h1>Saved backend runs</h1>
                  <p className="muted">Open any entry to see the stored explanation, response details, and request payload.</p>
                </div>
                <div className="history-controls">
                  <StatusPill tone="neutral">{historyEntries.length} entries</StatusPill>
                  <button type="button" className="soft-button inline" onClick={handleClearHistory} disabled={!historyEntries.length}>
                    Clear history
                  </button>
                </div>
              </div>

              {recentHistory.length ? (
                <div className="history-list">
                  {recentHistory.map((entry) => (
                    <HistoryCard
                      key={entry.history_id}
                      entry={entry}
                      detail={historyDetails[entry.history_id]}
                      loading={historyLoading[entry.history_id]}
                      onToggle={() => toggleHistoryDetails(entry.history_id)}
                    />
                  ))}
                </div>
              ) : (
                <article className="panel-card">
                  <p className="muted">No history yet. Run any tracker to persist a backend event.</p>
                </article>
              )}
            </section>
          ) : null}
        </main>
      </div>
    </div>
  );
}
