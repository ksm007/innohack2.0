import { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  askPolicy,
  buildIndexes,
  comparePolicies,
  diffPolicies,
  fetchDocuments,
  fetchGraphStatus,
  fetchIndexSettings,
  updateIndexSettings
} from "./api";

const DEFAULT_DRUG = "Infliximab";
const MAX_MESSAGES = 60;

const NAV_ITEMS = ["Policies", "Payers", "Analytics", "Archive"];
const SIDE_ITEMS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "review", label: "Review" },
  { id: "settings", label: "Settings" }
];

const WORKFLOWS = [
  {
    id: "coverage-scan",
    label: "Coverage scan",
    action: "compare",
    description: "Compare multiple payers for one therapy.",
    getQuestion: (drugName) =>
      `How do payers cover ${drugName} under the medical benefit, including prior authorization, preferred products, and step therapy?`
  },
  {
    id: "prior-auth-check",
    label: "Prior auth check",
    action: "ask",
    description: "Inspect one payer's authorization criteria.",
    getQuestion: (drugName, selectedPayers) =>
      `What prior authorization criteria does ${selectedPayers[0] || "the selected payer"} require for ${drugName}?`
  },
  {
    id: "policy-change-watch",
    label: "Policy change watch",
    action: "changes",
    description: "Compare two versions of a policy.",
    getQuestion: (drugName) =>
      `What changed between these policy versions for ${drugName}, and which changes are meaningful for coverage decisions?`
  }
];

const DEMO_SCENARIOS = [
  {
    id: "judge-primary",
    title: "Judge Demo",
    eyebrow: "Primary",
    workflowId: "coverage-scan",
    drugName: "Infliximab",
    payerFilters: ["Aetna", "Cigna", "UnitedHealthcare"],
    question:
      "How do Aetna, Cigna, and UnitedHealthcare differ in coverage, prior authorization, preferred products, and step therapy for infliximab under the medical benefit?",
    summary: "Best single-click storyline for the demo: evidence-backed payer comparison.",
    detail: "Compares three strong payer documents with graph summary.",
    accent: "blue"
  },
  {
    id: "aetna-ustekinumab",
    title: "Aetna Ustekinumab",
    eyebrow: "Ask",
    workflowId: "prior-auth-check",
    drugName: "Ustekinumab",
    payerFilters: ["Aetna"],
    question:
      "What prior authorization criteria does this payer require for ustekinumab, and what step therapy alternatives must be tried first?",
    summary: "Shows a clean, high-confidence prior auth extraction.",
    detail: "PageIndex retrieval surfaces criteria and step edits reliably.",
    accent: "amber"
  },
  {
    id: "cigna-rituximab",
    title: "Cigna Rituximab",
    eyebrow: "Ask",
    workflowId: "prior-auth-check",
    drugName: "Rituximab",
    payerFilters: ["Cigna"],
    question:
      "What prior authorization criteria apply for rituximab for non-oncology indications?",
    summary: "Good single-payer example for operational authorization logic.",
    detail: "Useful to show extraction from a focused Cigna policy.",
    accent: "teal"
  },
  {
    id: "uhc-infliximab-changes",
    title: "UHC Infliximab Changes",
    eyebrow: "Changes",
    workflowId: "policy-change-watch",
    drugName: "Infliximab",
    payerFilters: ["UnitedHealthcare"],
    question:
      "What changed between these policy versions, and which changes are meaningful for coverage decisions?",
    summary: "Version watch with narrative summary plus field-level deltas.",
    detail: "Uses the strongest known UHC infliximab version pair.",
    accent: "rose"
  }
];

function groupPayers(documents) {
  return [...new Set(documents.map((doc) => doc.payer))].filter(Boolean).sort();
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function formatList(items) {
  return items?.filter(Boolean).join(", ") || "none";
}

function countBy(items, resolver) {
  return items.reduce((counts, item) => {
    const key = resolver(item);
    if (!key) return counts;
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {});
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

function getDocumentLabel(documents, docId) {
  return documents.find((doc) => doc.doc_id === docId)?.policy_name || "Unknown document";
}

function buildCompareHighlights(rows = []) {
  if (!rows.length) return [];
  const coveredCount = rows.filter((row) => normalizeText(row.coverage).includes("covered")).length;
  const priorAuthCount = rows.filter((row) => normalizeText(row.prior_auth).startsWith("yes")).length;
  const stepCount = rows.filter((row) => normalizeText(row.step_therapy).startsWith("yes")).length;
  return [
    { label: "Covered", value: coveredCount, detail: `${rows.length} payer rows` },
    { label: "Prior auth", value: priorAuthCount, detail: "policies requiring PA" },
    { label: "Step therapy", value: stepCount, detail: "policies with step edits" }
  ];
}

function pickVersionPair(documents, drugName, preferredPayer = "") {
  const lowered = normalizeText(drugName);
  const preferred = normalizeText(preferredPayer);
  const filtered = documents.filter((doc) => {
    const policy = normalizeText(doc.policy_name);
    const likely = normalizeText(doc.likely_drug);
    const payer = normalizeText(doc.payer);
    const matchesDrug = lowered && (policy.includes(lowered) || likely.includes(lowered));
    const matchesPayer = !preferred || payer.includes(preferred);
    return matchesDrug && matchesPayer;
  });

  const grouped = new Map();
  for (const doc of filtered) {
    if (!doc.version_group) continue;
    const items = grouped.get(doc.version_group) || [];
    items.push(doc);
    grouped.set(doc.version_group, items);
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

function pickScenarioVersionPair(documents, scenario) {
  if (scenario.id === "uhc-infliximab-changes") {
    const exactOld = documents.find((doc) => doc.doc_id === "infliximab-remicade-inflectra");
    const exactNew = documents.find((doc) => doc.doc_id === "infliximab-remicade-inflectra-02012026");
    if (exactOld && exactNew) {
      return {
        oldDocId: exactOld.doc_id,
        newDocId: exactNew.doc_id
      };
    }
    return pickVersionPair(documents, scenario.drugName, scenario.payerFilters?.[0]);
  }
  return pickVersionPair(documents, scenario.drugName, scenario.payerFilters?.[0]);
}

function metricTrendLabel(graphStatus, indexSettings) {
  if (graphStatus?.connected && indexSettings?.enabled) return "Fully primed";
  if (graphStatus?.connected) return "Graph online";
  return "Local fallback";
}

function summarizeCoverage(rows = []) {
  if (!rows.length) return "Run the judge demo to surface payer differences.";
  const mostRestrictive = rows.find((row) => normalizeText(row.step_therapy).startsWith("yes")) || rows[0];
  return `${mostRestrictive.payer} shows the strongest utilization management signal in the current compare result.`;
}

function extractCriteriaPoints(record) {
  const points = [];
  if (record.prior_auth_criteria && normalizeText(record.prior_auth_criteria) !== "unknown") {
    points.push(record.prior_auth_criteria);
  }
  if (record.step_therapy && normalizeText(record.step_therapy) !== "unknown") {
    points.push(record.step_therapy);
  }
  if (record.site_of_care && normalizeText(record.site_of_care) !== "unknown") {
    points.push(record.site_of_care);
  }
  return points.slice(0, 3);
}

function statusTone(status = "") {
  const normalized = normalizeText(status);
  if (normalized === "complete" || normalized === "answered") return "success";
  if (normalized === "partial" || normalized === "review required") return "warning";
  return "neutral";
}

function Icon({ name }) {
  const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.75", strokeLinecap: "round", strokeLinejoin: "round" };
  if (name === "dashboard") {
    return (
      <svg {...common} aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="4" rx="1.5" />
        <rect x="14" y="10" width="7" height="11" rx="1.5" />
        <rect x="3" y="13" width="7" height="8" rx="1.5" />
      </svg>
    );
  }
  if (name === "review") {
    return (
      <svg {...common} aria-hidden="true">
        <path d="M4 5h16v14H4z" />
        <path d="M8 9h8" />
        <path d="M8 13h5" />
        <path d="M8 17h4" />
      </svg>
    );
  }
  if (name === "settings") {
    return (
      <svg {...common} aria-hidden="true">
        <circle cx="12" cy="12" r="3.5" />
        <path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 1 1-4 0v-.2a1 1 0 0 0-.7-.9 1 1 0 0 0-1.1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 1 1 0-4h.2a1 1 0 0 0 .9-.7 1 1 0 0 0-.2-1.1l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a2 2 0 1 1 4 0v.2a1 1 0 0 0 .7.9 1 1 0 0 0 1.1-.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6h.2a2 2 0 1 1 0 4h-.2a1 1 0 0 0-.9.7z" />
      </svg>
    );
  }
  if (name === "search") {
    return (
      <svg {...common} aria-hidden="true">
        <circle cx="11" cy="11" r="6" />
        <path d="m20 20-3.5-3.5" />
      </svg>
    );
  }
  if (name === "profile") {
    return (
      <svg {...common} aria-hidden="true">
        <path d="M20 21a8 8 0 0 0-16 0" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    );
  }
  if (name === "spark") {
    return (
      <svg {...common} aria-hidden="true">
        <path d="M12 3 13.9 8.1 19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" />
      </svg>
    );
  }
  if (name === "send") {
    return (
      <svg {...common} aria-hidden="true">
        <path d="m22 2-7 20-4-9-9-4 20-7Z" />
        <path d="M22 2 11 13" />
      </svg>
    );
  }
  return null;
}

function StatusPill({ tone = "neutral", children }) {
  return <span className={`status-pill ${tone}`}>{children}</span>;
}

function MetricTile({ label, value, detail, tone = "neutral" }) {
  return (
    <article className={`metric-tile ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function EvidenceList({ evidence }) {
  if (!evidence?.length) return <p className="muted">No evidence snippets returned.</p>;
  return (
    <div className="evidence-list">
      {evidence.map((item, index) => (
        <article key={`${item.page}-${index}`} className="evidence-card">
          <div className="evidence-meta">
            <span>Page {item.page}</span>
            <span>{item.section}</span>
            <span>{item.retrieval_method}</span>
          </div>
          <p>{item.snippet}</p>
        </article>
      ))}
    </div>
  );
}

function AskPreview({ records }) {
  return (
    <div className="message-stack">
      {records.map((record) => (
        <article key={record.doc_id} className="message-card">
          <div className="card-head">
            <div>
              <h4>{record.payer}</h4>
              <p className="muted">{record.policy_name}</p>
            </div>
            <StatusPill tone={statusTone(record.status)}>{record.status}</StatusPill>
          </div>
          <p className="message-summary">{record.answer}</p>
          <div className="signal-row">
            <span>Coverage: {record.coverage_status}</span>
            <span>PA: {record.prior_auth_required}</span>
            <span>Confidence: {record.confidence}</span>
          </div>
          {record.graph_context ? (
            <div className="context-panel">
              <strong>Graph context</strong>
              <p className="muted">{record.graph_context.status_message}</p>
              <p className="muted">Known payers: {formatList(record.graph_context.known_payers_for_drug)}</p>
            </div>
          ) : null}
          <EvidenceList evidence={record.evidence} />
        </article>
      ))}
    </div>
  );
}

function ComparePreview({ rows, graphSummary }) {
  const highlights = buildCompareHighlights(rows);
  return (
    <div className="message-stack">
      <div className="metric-row compact">
        {highlights.map((item) => (
          <MetricTile key={item.label} {...item} />
        ))}
      </div>
      {graphSummary ? (
        <div className="context-panel">
          <strong>Graph summary</strong>
          <p className="muted">{graphSummary.status_message}</p>
          <p className="muted">Payers: {formatList(graphSummary.payer_names)}</p>
        </div>
      ) : null}
      <div className="table-shell">
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
      <article className="message-card">
        <div className="card-head">
          <div>
            <h4>Change summary</h4>
            <p className="muted">
              {changeResult.old_record.payer} · {changeResult.old_record.policy_name}
            </p>
          </div>
          <StatusPill tone="warning">{changeResult.diffs.length} fields</StatusPill>
        </div>
        <p className="message-summary">{changeResult.narrative_summary}</p>
      </article>

      {changeResult.graph_summary ? (
        <article className="message-card subtle">
          <div className="card-head">
            <h4>Graph delta</h4>
            <StatusPill tone={changeResult.graph_summary.enabled ? "success" : "neutral"}>
              {changeResult.graph_summary.enabled ? "neo4j" : "fallback"}
            </StatusPill>
          </div>
          <p className="message-summary">{changeResult.graph_summary.summary}</p>
          <div className="signal-row">
            <span>Added indications: {formatList(changeResult.graph_summary.added_indications)}</span>
            <span>Removed indications: {formatList(changeResult.graph_summary.removed_indications)}</span>
          </div>
        </article>
      ) : null}

      <div className="diff-grid">
        {changeResult.diffs.map((diff) => (
          <article key={diff.field} className="diff-card">
            <div className="card-head">
              <h4>{diff.field}</h4>
              <StatusPill tone="neutral">{diff.change_type}</StatusPill>
            </div>
            <p className="muted">Old: {JSON.stringify(diff.old_value)}</p>
            <p>New: {JSON.stringify(diff.new_value)}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ message }) {
  return (
    <article className={`message-bubble ${message.role}`}>
      <div className="bubble-head">
        <span>{message.role === "user" ? "Analyst" : "Anton Copilot"}</span>
        <span>{message.timestamp}</span>
      </div>
      {message.title ? <h3>{message.title}</h3> : null}
      {message.text ? <p>{message.text}</p> : null}
      {message.kind === "ask" ? <AskPreview records={message.records} /> : null}
      {message.kind === "compare" ? <ComparePreview rows={message.rows} graphSummary={message.graphSummary} /> : null}
      {message.kind === "changes" ? <ChangesPreview changeResult={message.changeResult} /> : null}
      {message.kind === "system" && message.meta ? <p className="muted">{message.meta}</p> : null}
    </article>
  );
}

function HeroSpotlight({ compareResult, askResult, changeResult }) {
  if (compareResult?.rows?.length) {
    const lead = compareResult.rows[0];
    const secondary = compareResult.rows[1];
    const tertiary = compareResult.rows[2];
    return (
      <section className="spotlight-panel">
        <div className="prompt-chip">
          <span>Active insight</span>
          <p>{summarizeCoverage(compareResult.rows)}</p>
        </div>
        <div className="spotlight-grid">
          {[lead, secondary].filter(Boolean).map((row, index) => (
            <article key={`${row.payer}-${row.policy_name}`} className={`policy-spotlight ${index === 0 ? "primary" : "secondary"}`}>
              <div className="policy-topline">
                <div>
                  <span className="policy-micro">{row.payer}</span>
                  <h3>{row.coverage}</h3>
                </div>
                <StatusPill tone={index === 0 ? "neutral" : "warning"}>{index === 0 ? "Primary" : "Comparative"}</StatusPill>
              </div>
              <ul className="criteria-list">
                <li>{row.prior_auth}</li>
                <li>{row.step_therapy}</li>
                <li>{row.site_of_care}</li>
              </ul>
            </article>
          ))}
        </div>
        {tertiary ? (
          <div className="projection-card">
            <span>Additional payer</span>
            <strong>{tertiary.payer}</strong>
            <p>{tertiary.coverage}</p>
          </div>
        ) : null}
      </section>
    );
  }

  if (askResult?.records?.length) {
    const lead = askResult.records[0];
    return (
      <section className="spotlight-panel single">
        <div className="prompt-chip">
          <span>Current answer</span>
          <p>{lead.answer}</p>
        </div>
        <article className="ask-spotlight">
          <div className="policy-topline">
            <div>
              <span className="policy-micro">{lead.payer}</span>
              <h3>{lead.coverage_status}</h3>
            </div>
            <StatusPill tone={statusTone(lead.status)}>{lead.status}</StatusPill>
          </div>
          <ul className="criteria-list">
            {extractCriteriaPoints(lead).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </section>
    );
  }

  if (changeResult) {
    return (
      <section className="spotlight-panel single">
        <div className="prompt-chip">
          <span>Version watch</span>
          <p>{changeResult.narrative_summary}</p>
        </div>
        <article className="projection-card wide">
          <span>Changed fields</span>
          <strong>{changeResult.diffs.length}</strong>
          <p>{changeResult.graph_summary?.summary || "Narrative diff ready for review."}</p>
        </article>
      </section>
    );
  }

  return (
    <section className="spotlight-panel empty">
      <div className="prompt-chip">
        <span>Suggested move</span>
        <p>Run the Judge Demo for the strongest compare flow, then use Ask or Changes to drill deeper.</p>
      </div>
      <div className="projection-card wide muted-card">
        <span>System behavior</span>
        <strong>PageIndex + Graph</strong>
        <p>Evidence comes from structured PDF sections first, then the extracted rules are persisted for cross-payer analysis.</p>
      </div>
    </section>
  );
}

export default function App() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [drugName, setDrugName] = useState(DEFAULT_DRUG);
  const [question, setQuestion] = useState("");
  const [selectedPayers, setSelectedPayers] = useState([]);
  const [oldDocId, setOldDocId] = useState("");
  const [newDocId, setNewDocId] = useState("");
  const [graphStatus, setGraphStatus] = useState(null);
  const [indexSettings, setIndexSettings] = useState(null);
  const [compareResult, setCompareResult] = useState(null);
  const [askResult, setAskResult] = useState(null);
  const [changeResult, setChangeResult] = useState(null);
  const [indexResult, setIndexResult] = useState(null);
  const [messages, setMessages] = useState([]);
  const [activeWorkflowId, setActiveWorkflowId] = useState(WORKFLOWS[0].id);
  const [activeScenarioId, setActiveScenarioId] = useState("judge-primary");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isIndexing, setIsIndexing] = useState(false);
  const [isUpdatingIndexSettings, setIsUpdatingIndexSettings] = useState(false);

  const deferredDrugName = useDeferredValue(drugName);

  useEffect(() => {
    async function load() {
      try {
        const [docs, graph, indexConfig] = await Promise.all([
          fetchDocuments(),
          fetchGraphStatus(),
          fetchIndexSettings()
        ]);
        const payers = groupPayers(docs);
        const pair = pickVersionPair(docs, DEFAULT_DRUG, "UnitedHealthcare");
        const initialPayers = ["Aetna", "Cigna", "UnitedHealthcare"].filter((payer) => payers.includes(payer));

        setDocuments(docs);
        setGraphStatus(graph);
        setIndexSettings(indexConfig);
        setSelectedPayers(initialPayers.length ? initialPayers : payers.slice(0, 3));
        setQuestion(DEMO_SCENARIOS[0].question);
        setOldDocId(pair?.oldDocId || docs[0]?.doc_id || "");
        setNewDocId(pair?.newDocId || docs[1]?.doc_id || "");

        setMessages([
          createMessage("assistant", "system", {
            title: "Anton Rx analytics board ready",
            text: "Use the single-click demo cards for judge flows, or drive the backend manually from the analyst console.",
            meta: `${docs.length} documents loaded across ${payers.length} payers.`
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
    const pair = pickVersionPair(documents, drugName, selectedPayers[0]);
    if (pair) {
      setOldDocId(pair.oldDocId);
      setNewDocId(pair.newDocId);
    }
  }, [documents, drugName, selectedPayers]);

  const payers = useMemo(() => groupPayers(documents), [documents]);

  const activeWorkflow = useMemo(
    () => WORKFLOWS.find((workflow) => workflow.id === activeWorkflowId) || WORKFLOWS[0],
    [activeWorkflowId]
  );

  const activeScenario = useMemo(
    () => DEMO_SCENARIOS.find((scenario) => scenario.id === activeScenarioId) || DEMO_SCENARIOS[0],
    [activeScenarioId]
  );

  const matchingDocuments = useMemo(() => {
    const lowered = normalizeText(deferredDrugName);
    if (!lowered) return documents;
    return documents.filter((doc) => {
      const policy = normalizeText(doc.policy_name);
      const likely = normalizeText(doc.likely_drug);
      return policy.includes(lowered) || likely.includes(lowered);
    });
  }, [documents, deferredDrugName]);

  const compareHighlights = useMemo(
    () => buildCompareHighlights(compareResult?.rows || []),
    [compareResult]
  );

  const relatedDrugs = useMemo(() => {
    const counts = countBy(
      documents.filter((doc) => doc.likely_drug && normalizeText(doc.likely_drug) !== normalizeText(drugName)),
      (doc) => doc.likely_drug
    );
    return Object.entries(counts)
      .sort((left, right) => right[1] - left[1])
      .slice(0, 4)
      .map(([name]) => name);
  }, [documents, drugName]);

  function appendMessage(msg) {
    setMessages((current) => [...current, msg].slice(-MAX_MESSAGES));
  }

  function appendErrorMessage(message) {
    appendMessage(createMessage("assistant", "system", { title: "Request failed", text: message }));
  }

  function selectWorkflow(workflow) {
    setActiveWorkflowId(workflow.id);
    setQuestion(workflow.getQuestion(drugName, selectedPayers));
  }

  function togglePayer(payer) {
    setSelectedPayers((current) =>
      current.includes(payer) ? current.filter((value) => value !== payer) : [...current, payer]
    );
  }

  async function executeWorkflow({
    workflow,
    nextDrugName,
    nextQuestion,
    nextPayers,
    nextOldDocId,
    nextNewDocId,
    messageTitle
  }) {
    const trimmedQuestion = nextQuestion.trim();
    if (!trimmedQuestion) return;

    setError("");
    setNotice("");
    setIsSubmitting(true);

    appendMessage(
      createMessage("user", "text", {
        title: messageTitle || workflow.label,
        text: trimmedQuestion
      })
    );

    try {
      if (workflow.action === "ask") {
        const result = await askPolicy({
          drug_name: nextDrugName,
          question: trimmedQuestion,
          payer_filters: nextPayers
        });
        setAskResult(result);
        appendMessage(
          createMessage("assistant", "ask", {
            title: "Policy answer",
            text: `Reviewed ${result.records.length} payer policies for ${nextDrugName}.`,
            records: result.records
          })
        );
        return;
      }

      if (workflow.action === "compare") {
        const result = await comparePolicies({
          drug_name: nextDrugName,
          question: trimmedQuestion,
          payer_filters: nextPayers
        });
        setCompareResult(result);
        appendMessage(
          createMessage("assistant", "compare", {
            title: "Coverage comparison",
            text: `Compared ${result.rows.length} normalized payer rows for ${nextDrugName}.`,
            rows: result.rows,
            graphSummary: result.graph_summary || null
          })
        );
        return;
      }

      const result = await diffPolicies({
        drug_name: nextDrugName,
        old_doc_id: nextOldDocId,
        new_doc_id: nextNewDocId,
        question: trimmedQuestion
      });
      setChangeResult(result);
      appendMessage(
        createMessage("assistant", "changes", {
          title: "Policy change watch",
          text: `Compared ${getDocumentLabel(documents, nextOldDocId)} against ${getDocumentLabel(documents, nextNewDocId)}.`,
          changeResult: result
        })
      );
    } catch (requestError) {
      setError(requestError.message);
      appendErrorMessage(requestError.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRunWorkflow() {
    await executeWorkflow({
      workflow: activeWorkflow,
      nextDrugName: drugName,
      nextQuestion: question,
      nextPayers: selectedPayers,
      nextOldDocId: oldDocId,
      nextNewDocId: newDocId,
      messageTitle: activeWorkflow.label
    });
  }

  async function runScenario(scenario) {
    const workflow = WORKFLOWS.find((item) => item.id === scenario.workflowId) || WORKFLOWS[0];
    const scenarioPair = workflow.action === "changes" ? pickScenarioVersionPair(documents, scenario) : null;

    if (workflow.action === "changes" && !scenarioPair) {
      setError("No version pair could be matched for that demo scenario.");
      return;
    }

    setActiveScenarioId(scenario.id);
    setActiveWorkflowId(workflow.id);
    setDrugName(scenario.drugName);
    setQuestion(scenario.question);
    setSelectedPayers(scenario.payerFilters || []);
    if (scenarioPair) {
      setOldDocId(scenarioPair.oldDocId);
      setNewDocId(scenarioPair.newDocId);
    }

    await executeWorkflow({
      workflow,
      nextDrugName: scenario.drugName,
      nextQuestion: scenario.question,
      nextPayers: scenario.payerFilters || [],
      nextOldDocId: scenarioPair?.oldDocId || oldDocId,
      nextNewDocId: scenarioPair?.newDocId || newDocId,
      messageTitle: scenario.title
    });
  }

  async function handleToggleIndexWarmup() {
    if (!indexSettings) return;
    setError("");
    setNotice("");
    setIsUpdatingIndexSettings(true);

    try {
      const next = await updateIndexSettings({ enabled: !indexSettings.enabled });
      setIndexSettings(next);
      setNotice(next.detail);
    } catch (requestError) {
      setError(requestError.message);
      appendErrorMessage(requestError.message);
    } finally {
      setIsUpdatingIndexSettings(false);
    }
  }

  async function handleBuildIndexes() {
    setError("");
    setNotice("");
    setIsIndexing(true);

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
      appendErrorMessage(requestError.message);
    } finally {
      setIsIndexing(false);
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
    setNotice("Downloaded compare CSV.");
  }

  async function copyCompareMarkdown() {
    if (!compareResult?.rows?.length) return;
    const header = "| Payer | Coverage | Prior Auth | Step Therapy | Site of Care | Effective Date | Status |";
    const divider = "|---|---|---|---|---|---|---|";
    const rows = compareResult.rows.map(
      (row) =>
        `| ${row.payer} | ${row.coverage} | ${row.prior_auth} | ${row.step_therapy} | ${row.site_of_care} | ${row.effective_date} | ${row.status} |`
    );
    await navigator.clipboard.writeText([header, divider, ...rows].join("\n"));
    setNotice("Copied compare markdown table.");
  }

  if (loading) {
    return <div className="loading-screen">Loading Anton Rx Track analytics workspace...</div>;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <span className="brand-mark">Anton Rx Track</span>
        </div>
        <nav className="top-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <button key={item} type="button" className={item === "Analytics" ? "top-nav-item active" : "top-nav-item"}>
              {item}
            </button>
          ))}
        </nav>
        <div className="top-tools">
          <label className="search-shell" aria-label="Drug search">
            <Icon name="search" />
            <input
              value={drugName}
              onChange={(event) => setDrugName(event.target.value)}
              placeholder="Search drug codes..."
            />
          </label>
          <button type="button" className="avatar-button" aria-label="Profile">
            <Icon name="profile" />
          </button>
        </div>
      </header>

      <div className="dashboard-layout">
        <aside className="left-rail">
          <section className="identity-card">
            <strong>Anton Rx</strong>
            <span>Clinical Editorial</span>
          </section>

          <nav className="side-nav" aria-label="Workspace">
            {SIDE_ITEMS.map((item, index) => (
              <button key={item.id} type="button" className={index === 0 ? "side-item active" : "side-item"}>
                <Icon name={item.id} />
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          <section className="rail-panel">
            <div className="panel-header">
              <span className="panel-eyebrow">Active parameters</span>
            </div>

            <label className="field-block">
              <span>Drug focus</span>
              <input value={drugName} onChange={(event) => setDrugName(event.target.value)} />
            </label>

            <div className="field-block">
              <span>Payer benchmark</span>
              <div className="check-list">
                {payers.map((payer) => (
                  <label key={payer} className="check-row">
                    <input
                      type="checkbox"
                      checked={selectedPayers.includes(payer)}
                      onChange={() => togglePayer(payer)}
                    />
                    <span>{payer}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="field-block">
              <span>Workflow</span>
              <div className="workflow-stack">
                {WORKFLOWS.map((workflow) => (
                  <button
                    key={workflow.id}
                    type="button"
                    className={workflow.id === activeWorkflowId ? "workflow-pill active" : "workflow-pill"}
                    onClick={() => selectWorkflow(workflow)}
                  >
                    <strong>{workflow.label}</strong>
                    <small>{workflow.description}</small>
                  </button>
                ))}
              </div>
            </div>
          </section>

          <section className="rail-panel muted">
            <div className="panel-header">
              <span className="panel-eyebrow">Judge path</span>
            </div>
            <p className="rail-copy">Single-click strongest storyline for the live demo.</p>
            <button
              type="button"
              className="primary-action"
              onClick={() => runScenario(DEMO_SCENARIOS[0])}
              disabled={isSubmitting}
            >
              {isSubmitting && activeScenarioId === "judge-primary" ? "Running..." : "Launch Judge Demo"}
            </button>
          </section>
        </aside>

        <main className="main-stage">
          <section className="headline-row">
            <div className="headline-copy">
              <span className="panel-eyebrow">Medical benefit policy tracker</span>
              <h1>Medical Benefit Drug Policy Tracker</h1>
              <p>
                Structured retrieval with PageIndex, payer comparison with graph context, and one-click demo flows mapped to the strongest validated backend cases.
              </p>
            </div>
            <div className="headline-prompt">
              <span>Current prompt</span>
              <p>{question || activeScenario.question}</p>
            </div>
          </section>

          <section className="scenario-strip" aria-label="One-click demos">
            {DEMO_SCENARIOS.map((scenario) => (
              <article
                key={scenario.id}
                className={scenario.id === activeScenarioId ? `scenario-card ${scenario.accent} active` : `scenario-card ${scenario.accent}`}
              >
                <div className="scenario-head">
                  <span>{scenario.eyebrow}</span>
                  <button
                    type="button"
                    className="scenario-run"
                    onClick={() => runScenario(scenario)}
                    disabled={isSubmitting}
                  >
                    {isSubmitting && activeScenarioId === scenario.id ? "Running..." : "Run"}
                  </button>
                </div>
                <h2>{scenario.title}</h2>
                <p>{scenario.summary}</p>
                <small>{scenario.detail}</small>
              </article>
            ))}
          </section>

          <HeroSpotlight compareResult={compareResult} askResult={askResult} changeResult={changeResult} />

          <section className="console-card">
            <div className="console-head">
              <div>
                <span className="panel-eyebrow">Analyst console</span>
                <h2>Drive the backend directly</h2>
              </div>
              <StatusPill tone="neutral">{activeWorkflow.label}</StatusPill>
            </div>

            <div className="console-grid">
              <label className="field-block">
                <span>Question</span>
                <textarea
                  value={question}
                  rows={4}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                      event.preventDefault();
                      handleRunWorkflow();
                    }
                  }}
                />
              </label>

              <div className="version-stack">
                <label className="field-block">
                  <span>Older version</span>
                  <select value={oldDocId} onChange={(event) => setOldDocId(event.target.value)}>
                    {documents.map((doc) => (
                      <option key={doc.doc_id} value={doc.doc_id}>
                        {doc.policy_name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field-block">
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
            </div>

            <div className="console-actions">
              <span>Press Cmd/Ctrl + Enter or use a demo card for single-click execution.</span>
              <button type="button" className="run-button" onClick={handleRunWorkflow} disabled={isSubmitting}>
                {isSubmitting ? "Running..." : `Run ${activeWorkflow.label}`}
                <Icon name="send" />
              </button>
            </div>
          </section>

          <section className="thread-panel">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </section>
        </main>

        <aside className="right-rail">
          <section className="rail-panel insight">
            <div className="panel-header">
              <span className="panel-eyebrow">Market insights</span>
            </div>

            <div className="metric-column">
              <MetricTile
                label="Runtime"
                value={graphStatus?.connected ? "Neo4j" : "SQLite"}
                detail={graphStatus?.detail || "Local-first mode"}
                tone={graphStatus?.connected ? "success" : "neutral"}
              />
              <MetricTile
                label="Indexer"
                value={indexSettings?.enabled ? "Autobuild on" : "Manual"}
                detail={indexSettings?.detail || "PageIndex warmup"}
                tone={indexSettings?.enabled ? "warning" : "neutral"}
              />
              <MetricTile
                label="Scenario state"
                value={metricTrendLabel(graphStatus, indexSettings)}
                detail={activeScenario.title}
                tone="neutral"
              />
            </div>
          </section>

          <section className="rail-panel insight">
            <div className="panel-header">
              <span className="panel-eyebrow">Coverage pulse</span>
            </div>

            {compareHighlights.length ? (
              <div className="metric-column">
                {compareHighlights.map((item) => (
                  <MetricTile key={item.label} {...item} />
                ))}
              </div>
            ) : (
              <p className="muted">Run the judge demo or any compare scenario to populate payer metrics.</p>
            )}

            {compareResult?.graph_summary ? (
              <div className="context-panel">
                <strong>Graph summary</strong>
                <p className="muted">{compareResult.graph_summary.status_message}</p>
                <p className="muted">Payers: {formatList(compareResult.graph_summary.payer_names)}</p>
              </div>
            ) : null}

            {compareResult?.rows?.length ? (
              <div className="button-row">
                <button type="button" className="secondary-action" onClick={downloadCompareCsv}>
                  Download CSV
                </button>
                <button type="button" className="secondary-action" onClick={copyCompareMarkdown}>
                  Copy Markdown
                </button>
              </div>
            ) : null}
          </section>

          <section className="rail-panel insight">
            <div className="panel-header">
              <span className="panel-eyebrow">Operations</span>
            </div>

            <div className="field-block">
              <span>Background warmup</span>
              <button
                type="button"
                className={indexSettings?.enabled ? "workflow-pill active" : "workflow-pill"}
                onClick={handleToggleIndexWarmup}
                disabled={isUpdatingIndexSettings}
              >
                <strong>{isUpdatingIndexSettings ? "Updating..." : indexSettings?.enabled ? "Autobuild on" : "Autobuild off"}</strong>
                <small>Build missing PageIndex trees after backend startup.</small>
              </button>
            </div>

            <button type="button" className="secondary-action full" onClick={handleBuildIndexes} disabled={isIndexing}>
              {isIndexing ? "Warming indexes..." : "Warm PageIndex for current drug"}
            </button>

            {indexResult?.results?.length ? (
              <div className="mini-log">
                {indexResult.results.slice(0, 5).map((result) => (
                  <div key={result.doc_id} className="mini-log-row">
                    <span>{result.doc_id}</span>
                    <StatusPill tone={result.status === "completed" || result.status === "cached" ? "success" : "warning"}>
                      {result.status}
                    </StatusPill>
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <section className="rail-panel insight">
            <div className="panel-header">
              <span className="panel-eyebrow">Related molecules</span>
            </div>

            <ul className="related-list">
              {relatedDrugs.length ? (
                relatedDrugs.map((item) => (
                  <li key={item}>
                    <span>{item}</span>
                    <span>→</span>
                  </li>
                ))
              ) : (
                <li>
                  <span>No related molecules surfaced yet.</span>
                </li>
              )}
            </ul>

            <div className="visual-card">
              <div className="visual-noise" />
              <p>
                “Structured retrieval keeps the evidence anchored to the active policy sections instead of background references.”
              </p>
            </div>
          </section>

          <section className="rail-panel insight">
            <div className="panel-header">
              <span className="panel-eyebrow">Corpus slice</span>
            </div>
            <div className="document-list">
              {(matchingDocuments.length ? matchingDocuments : documents).slice(0, 6).map((doc) => (
                <article key={doc.doc_id} className="document-card">
                  <div className="card-head">
                    <div>
                      <h4>{doc.payer}</h4>
                      <p className="muted">{doc.policy_name}</p>
                    </div>
                    <StatusPill tone="neutral">{doc.version_label || "current"}</StatusPill>
                  </div>
                  <div className="signal-row">
                    <span>{doc.document_pattern}</span>
                    <span>{doc.likely_drug || "multi-drug"}</span>
                  </div>
                </article>
              ))}
            </div>
          </section>

          {notice ? <div className="notice-box">{notice}</div> : null}
          {error ? <div className="error-box">{error}</div> : null}
        </aside>
      </div>
    </div>
  );
}
