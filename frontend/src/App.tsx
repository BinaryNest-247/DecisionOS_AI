import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  BarChart3,
  BrainCircuit,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Database,
  FileCheck2,
  FileText,
  Gauge,
  GitBranch,
  Menu,
  MessageSquareText,
  Play,
  Plus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import {
  Bar,
  BarChart,
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, api } from "./services/api";
import type { Approval, ApprovalStatus, AnalyticsResult, DataResponse, Decision, Lead, LLMProviderName, LLMProviderStatus, SimulationResult } from "./types";

type View =
  | "overview"
  | "data"
  | "analytics"
  | "ask"
  | "decisions"
  | "evidence"
  | "simulator"
  | "approval"
  | "evaluation";
type DecisionLoadState = "loading" | "ready" | "none" | "error" | "stale";
const CURRENT_DECISION_STORAGE_KEY = "decisionos_current_decision_id";
const decisionViews: View[] = ["decisions", "evidence", "simulator", "approval"];
const navigation: Array<{ id: View; label: string; icon: typeof Activity }> = [
  { id: "overview", label: "Overview", icon: BarChart3 },
  { id: "data", label: "Business Data", icon: Database },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "ask", label: "Ask DecisionOS", icon: MessageSquareText },
  { id: "decisions", label: "Decisions", icon: GitBranch },
  { id: "evidence", label: "Evidence & Trace", icon: FileCheck2 },
  { id: "simulator", label: "What-If Simulator", icon: SlidersHorizontal },
  { id: "approval", label: "Human Approval", icon: ShieldCheck },
  { id: "evaluation", label: "Evaluation", icon: Gauge },
];
const examples = [
  "Which 10 leads should our sales team contact first this week?",
  "Which customers are at risk?",
  "Where is our biggest revenue opportunity?",
  "Which inactive customers should we re-engage?",
  "What changed in our sales performance?",
];
const factorLabels: Record<string, string> = {
  revenue: "Revenue importance",
  engagement: "Engagement",
  recency: "Recent activity",
  purchases: "Purchase history",
  status: "Lead status",
};
const chartColors = ["#e6ad52", "#6fa99a", "#9b9d9f"];

function money(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}
function compactMoney(value: number) {
  return value >= 100000 ? `₹${(value / 100000).toFixed(1)}L` : money(value);
}

function rebalanceWeights(
  weights: Record<string, number>,
  selected: string,
  value: number,
) {
  const otherFactors = Object.keys(weights).filter(
    (factor) => factor !== selected,
  );
  const remaining = 100 - value;
  const otherTotal = otherFactors.reduce(
    (sum, factor) => sum + weights[factor],
    0,
  );
  const nextWeights = { ...weights, [selected]: value };
  const exactShares = otherFactors.map((factor) => ({
    factor,
    exact:
      otherTotal > 0
        ? (weights[factor] / otherTotal) * remaining
        : remaining / otherFactors.length,
  }));
  let distributed = 0;
  for (const share of exactShares) {
    nextWeights[share.factor] = Math.floor(share.exact);
    distributed += nextWeights[share.factor];
  }
  exactShares
    .sort((left, right) => (right.exact % 1) - (left.exact % 1))
    .slice(0, remaining - distributed)
    .forEach(({ factor }) => {
      nextWeights[factor] += 1;
    });
  return nextWeights;
}

function PageHeading({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="page-heading">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  );
}

function DecisionContext({ decision, filename, status }: { decision: Decision; filename: string; status: ApprovalStatus }) {
  return (
    <div className="decision-context">
      <div><span>CURRENT DECISION</span><strong>{decision.id}</strong></div>
      <div><span>DATASET</span><strong>{decision.trace_details?.dataset_filename ?? filename}</strong></div>
      <div><span>STATUS</span><strong>{status.toUpperCase()}</strong></div>
      <div><span>TRACE / CREATED</span><strong>{decision.trace.length} steps · {new Date(decision.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</strong></div>
    </div>
  );
}

function App() {
  const [view, setView] = useState<View>("overview");
  const [mobileMenu, setMobileMenu] = useState(false);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [data, setData] = useState<DataResponse | null>(null);
  const [llmProviderStatus, setLlmProviderStatus] = useState<LLMProviderStatus | null>(null);
  const [analyticsResult, setAnalyticsResult] = useState<AnalyticsResult | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [decisionLoadState, setDecisionLoadState] = useState<DecisionLoadState>("loading");
  const [decisionLoadError, setDecisionLoadError] = useState("");
  const [activeLead, setActiveLead] = useState<Lead | null>(null);
  const [question, setQuestion] = useState(examples[0]);
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({
    revenue: 30,
    engagement: 25,
    recency: 20,
    purchases: 15,
    status: 10,
  });
  const [approvalState, setApprovalState] = useState<ApprovalStatus>("pending");
  const [approval, setApproval] = useState<Approval | null>(null);
  const [approvalNote, setApprovalNote] = useState("");
  const [modifiedRecommendation, setModifiedRecommendation] = useState(
    "Contact the highest-priority lead first.",
  );
  const [evaluation, setEvaluation] = useState<Awaited<
    ReturnType<typeof api.evaluation>
  > | null>(null);
  const [uploadSteps, setUploadSteps] = useState<string[]>([]);
  const [dragActive, setDragActive] = useState(false);

  const clearCurrentDecision = () => {
    localStorage.removeItem(CURRENT_DECISION_STORAGE_KEY);
    setDecision(null);
    setActiveLead(null);
    setSimulation(null);
    setApproval(null);
    setApprovalState("pending");
    setDecisionLoadState("none");
    setDecisionLoadError("");
  };

  const loadCurrentDecision = async (
    expectedDatasetId?: string,
    openDecisionView = false,
    forceReload = false,
  ): Promise<Decision | null> => {
    if (decision && !forceReload && (!expectedDatasetId || decision.dataset_id === expectedDatasetId)) {
      setDecisionLoadState("ready");
      return decision;
    }
    setDecisionLoadState("loading");
    setDecisionLoadError("");
    try {
      let activeDatasetId = expectedDatasetId;
      if (!activeDatasetId) {
        const currentData = data ?? await api.summary();
        if (!data) setData(currentData);
        activeDatasetId = currentData.summary.dataset_id;
      }
<<<<<<< HEAD
      if (!activeDatasetId) {
        clearCurrentDecision();
        if (openDecisionView && view === "overview") setView("decisions");
        return null;
      }
=======
>>>>>>> 8e03c96660b8785c021372d016b8b39ca7766d71

      const queryDecisionId = new URLSearchParams(window.location.search).get("decision");
      const storedDecisionId = localStorage.getItem(CURRENT_DECISION_STORAGE_KEY);
      const candidateId = queryDecisionId || storedDecisionId;
      let restored: Decision | null = null;
      let restoredApproval: Approval | null = null;

      if (candidateId) {
        try {
          restored = await api.getDecision(candidateId);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            localStorage.removeItem(CURRENT_DECISION_STORAGE_KEY);
          }
        }
      }
      if (!restored) {
        try {
          const latest = await api.latestDecision();
          if (latest) {
            restored = latest.decision;
            restoredApproval = latest.approval;
          }
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            clearCurrentDecision();
            if (openDecisionView && view === "overview") setView("decisions");
            return null;
          }
          throw error;
        }
      }

      if (!restored) {
        clearCurrentDecision();
        if (openDecisionView && view === "overview") setView("decisions");
        return null;
      }

      if (activeDatasetId && restored.dataset_id !== activeDatasetId) {
        try {
          const latest = await api.latestDecision();
          if (latest && latest.decision.id !== restored.id && latest.decision.dataset_id === activeDatasetId) {
            restored = latest.decision;
            restoredApproval = latest.approval;
          }
        } catch {
          // Keep the stale decision message when no usable latest decision exists.
        }
      }
      if (activeDatasetId && restored.dataset_id !== activeDatasetId) {
        localStorage.removeItem(CURRENT_DECISION_STORAGE_KEY);
        setDecision(null);
        setActiveLead(null);
        setSimulation(null);
        setApproval(null);
        setApprovalState("pending");
        setDecisionLoadState("stale");
        setDecisionLoadError("This decision belongs to a different dataset. Please run a new analysis.");
        if (openDecisionView && view === "overview") setView("decisions");
        return null;
      }

      if (!restoredApproval) {
        try {
          const approvalResponse = await api.getApproval(restored.id);
          restoredApproval = approvalResponse.approval;
        } catch {
          restoredApproval = null;
        }
      }
      localStorage.setItem(CURRENT_DECISION_STORAGE_KEY, restored.id);
      setDecision(restored);
      setActiveLead(restored.leads[0] ?? null);
      setSimulation(null);
      setWeights(Object.fromEntries(Object.entries(restored.weights).map(([factor, value]) => [factor, Math.round(value * 100)])));
      setApproval(restoredApproval);
      setApprovalState(restoredApproval?.action === "approve" ? "approved" : restoredApproval?.action === "modify" ? "modified" : restoredApproval?.action === "reject" ? "rejected" : "pending");
      setApprovalNote(restoredApproval?.note ?? "");
      setModifiedRecommendation(restoredApproval?.recommendation ?? restored.recommendation);
      setDecisionLoadState("ready");
      if (openDecisionView && view === "overview") setView("decisions");
      return restored;
    } catch (error) {
      setDecisionLoadState("error");
      setDecisionLoadError(error instanceof Error ? error.message : "Decision could not be restored. Check the backend and try again.");
      return null;
    }
  };

  useEffect(() => {
    api
      .health()
      .then(() => setOnline(true))
      .catch(() => setOnline(false));
    api
      .summary()
      .then((result) => {
        setData(result);
        setQuestion((current) => current === examples[0] ? result.summary.supports_lead_decisions ? examples[0] : result.summary.suggested_questions[0] ?? current : current);
        const hadStoredDecision = Boolean(localStorage.getItem(CURRENT_DECISION_STORAGE_KEY) || new URLSearchParams(window.location.search).get("decision"));
        void loadCurrentDecision(result.summary.dataset_id, hadStoredDecision);
      })
      .catch(() => setData(null));
    api
      .evaluation()
      .then(setEvaluation)
      .catch(() => undefined);
    api.llmProviders().then(setLlmProviderStatus).catch(() => undefined);
  }, []);

  const run = async <T,>(
    action: () => Promise<T>,
    onSuccess: (result: T) => void,
    success?: string,
  ) => {
    setBusy(true);
    setNotice("");
    try {
      onSuccess(await action());
      if (success) setNotice(success);
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "The request could not be completed.",
      );
    } finally {
      setBusy(false);
    }
  };
  const refreshData = () => api.summary().then((result) => { setData(result); return result }).catch(() => undefined);
  const loadDemo = () =>
    run(
      api.loadDemo,
      async () => {
        await refreshData();
        clearCurrentDecision();
        setAnalyticsResult(null);
        setSimulation(null);
        setOnline(true);
      },
      "Demo dataset active.",
    );
<<<<<<< HEAD
  const deleteActiveDataset = () => {
    const datasetId = data?.summary.dataset_id;
    if (!datasetId) return;
    run(
      async () => {
        await api.deleteDataset(datasetId);
        return api.summary();
      },
      (result) => {
        setData(result);
        setAnalyticsResult(null);
        clearCurrentDecision();
        setApprovalNote("");
        setModifiedRecommendation("Contact the highest-priority lead first.");
        setWeights({ revenue: 30, engagement: 25, recency: 20, purchases: 15, status: 10 });
      },
      "Dataset deleted.",
    );
  };
=======
>>>>>>> 8e03c96660b8785c021372d016b8b39ca7766d71
  const analyze = () => {
    const decisionQuestion = /contact|priorit|sales team|recommend|re-engage|reengage/i.test(question);
    if (decisionQuestion && data?.summary.supports_lead_decisions) {
      return run(() => api.analyze(question), (result) => {
        setDecision(result);
        localStorage.setItem(CURRENT_DECISION_STORAGE_KEY, result.id);
        setActiveLead(result.leads[0] ?? null);
        setSimulation(null);
        setApproval(null);
        setApprovalState("pending");
        setApprovalNote("");
        setModifiedRecommendation(result.recommendation);
        setDecisionLoadState("ready");
        setDecisionLoadError("");
        setView("decisions");
      });
    }
    return run(() => api.analytics(question), (result) => {
      setAnalyticsResult(result);
      setView("analytics");
    });
  };
  const upload = (file?: File) => {
    if (!file) return;
    setUploadSteps(["Uploading file…"]);
    setView("data");
    run(
      () => api.upload(file),
      async (result) => {
        setUploadSteps(["✓ File uploaded", "✓ Dataset parsed", "✓ Data analyzed", "✓ Ready for questions"]);
        const active = await refreshData();
        clearCurrentDecision();
        setAnalyticsResult(null);
        if (active && !active.summary.supports_lead_decisions) {
          setQuestion(active.summary.suggested_questions[0] ?? "Are there any missing values?");
        }
        setNotice(`Active dataset: ${result.filename}`);
      },
    );
  };
  const changeSheet = (sheetName: string) => run(() => api.selectSheet(sheetName), (result) => {
    setData(result);
    clearCurrentDecision();
    setAnalyticsResult(null);
    setSimulation(null);
  }, `Active sheet: ${sheetName}`);
  const changeLLMProvider = (provider: LLMProviderName) =>
    run(() => api.selectLLMProvider(provider), setLlmProviderStatus, `${provider} selected.`);
  const simulate = () =>
    decision && run(() => api.simulate(decision.id, weights), setSimulation);
  const sendApproval = (action: "approve" | "modify" | "reject") => {
    if (!decision) {
      setNotice("Run an analysis before sending a decision for approval.");
      return;
    }
    if (action === "reject" && !approvalNote.trim()) {
      setNotice("A rejection reason is required.");
      return;
    }
    if (action === "modify" && !modifiedRecommendation.trim()) {
      setNotice("A modified recommendation is required.");
      return;
    }
    run(
      () =>
        api.approve({
          decision_id: decision.id,
          action,
          note: approvalNote,
          modified_recommendation:
            action === "modify" ? modifiedRecommendation : undefined,
        }),
      (result) => {
        setApproval(result.approval);
        setApprovalState(action === "approve" ? "approved" : action === "modify" ? "modified" : "rejected");
        setApprovalNote(result.approval.note);
        if (action === "modify" && result.approval.recommendation) setModifiedRecommendation(result.approval.recommendation);
        setNotice("Human approval recorded. No external action was executed.");
      },
    );
  };

  const distribution = data
    ? data.summary.supports_lead_decisions
      ? [
        { name: "High", value: data.summary.priority_distribution.HIGH ?? 0 },
        {
          name: "Medium",
          value: data.summary.priority_distribution.MEDIUM ?? 0,
        },
        { name: "Low", value: data.summary.priority_distribution.LOW ?? 0 },
      ]
      : data.summary.category_distribution
    : [];
  const askSuggestions = data?.summary.supports_lead_decisions
    ? [examples[0], ...data.summary.suggested_questions.filter((item) => item !== examples[0])].slice(0, 5)
    : data?.summary.suggested_questions.length
      ? data.summary.suggested_questions
      : examples;
  const title =
    navigation.find((item) => item.id === view)?.label ?? "Overview";

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileMenu ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark">
            <BrainCircuit size={21} strokeWidth={1.7} />
          </div>
          <div>
            <strong>
              DECISION<span>OS</span>
            </strong>
            <small>AI DECISION ENGINE</small>
          </div>
          <button
            className="mobile-close icon-button"
            aria-label="Close navigation"
            onClick={() => setMobileMenu(false)}
          >
            <X size={18} />
          </button>
        </div>
        <div className="workspace-label">
          WORKSPACE <ChevronDown size={13} />
        </div>
        <nav aria-label="Main navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${view === id ? "active" : ""}`}
              onClick={() => {
                setView(id);
                setMobileMenu(false);
                if (decisionViews.includes(id)) void loadCurrentDecision(data?.summary.dataset_id);
              }}
            >
              <Icon size={17} strokeWidth={1.7} />
              <span>{label}</span>
              {id === "decisions" && decision && (
                <span className="nav-count">1</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="system-status">
            <span className={`status-dot ${online ? "" : "offline"}`} />
            <div>
              <strong>{online ? "System online" : "API not connected"}</strong>
              <small>
                {online ? "All services operational" : "Start FastAPI on :8000"}
              </small>
            </div>
          </div>
          <div className="profile">
            <div className="avatar">JD</div>
            <div>
              <strong>Jordan Davis</strong>
              <small>Decision maker</small>
            </div>
            <CircleHelp size={16} />
          </div>
        </div>
      </aside>
      {mobileMenu && (
        <button
          className="mobile-scrim"
          aria-label="Close menu"
          onClick={() => setMobileMenu(false)}
        />
      )}

      <main className="main-area">
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            aria-label="Open navigation"
            onClick={() => setMobileMenu(true)}
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumb">
            DecisionOS <span>/</span> <strong>{title}</strong>
          </div>
          <div className="topbar-actions">
            <span className="top-date">
              <Clock3 size={14} /> LIVE PROTOTYPE
            </span>
            <button className="top-load" onClick={loadDemo}>
              <Plus size={15} /> Load demo data
            </button>
          </div>
        </header>
        <div className="content-wrap">
          {notice && (
            <div className="notice" role="status">
              <span>{notice}</span>
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {view === "overview" && (
            <>
              <section className="overview-intro">
                <div>
                  <span className="eyebrow">
                    PS-04 / AI DECISION ENGINE FOR BUSINESS DATA
                  </span>
                  <h1>
                    From scattered data
                    <br />
                    <em>to confident decisions.</em>
                  </h1>
                  <p>Ask. Analyze. Simulate. Decide.</p>
                  <div className="intro-actions">
                    <button
                      className="primary-button"
                      onClick={() => setView("ask")}
                    >
                      Explore demo <ArrowRight size={16} />
                    </button>
                    <button className="quiet-button" onClick={loadDemo}>
                      <Database size={15} /> Load demo data
                    </button>
                  </div>
                </div>
                <div className="workflow">
                  <div className="workflow-title">
                    <span>DECISION FLOW</span>
                    <span className="workflow-live">
                      <span className="status-dot" /> READY
                    </span>
                  </div>
                  <div className="workflow-steps">
                    {[
                      "DATA",
                      "ANALYZE",
                      "EVIDENCE",
                      "DECISION",
                      "SIMULATE",
                      "APPROVE",
                    ].map((step, index) => (
                      <div className="workflow-step" key={step}>
                        <span
                          className={
                            index === 3 ? "step-node highlighted" : "step-node"
                          }
                        >
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span>{step}</span>
                        {index < 5 && (
                          <ArrowRight className="workflow-arrow" size={13} />
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="workflow-foot">
                    <span>SCATTERED BUSINESS DATA</span>
                    <ArrowRight size={14} />
                    <span>CONFIDENT ACTION</span>
                  </div>
                </div>
              </section>
              <div className="metrics-grid">
                <Metric
                  label="Business records"
                  value={data?.summary.rows.toLocaleString() ?? "—"}
                  icon={<BriefcaseBusiness size={17} />}
                  foot="Loaded from connected dataset"
                />
                <Metric
                  label={data?.summary.supports_lead_decisions ? "High priority" : "Data profile"}
                  value={
                    data?.summary.supports_lead_decisions ? data.summary.high_priority_leads.toLocaleString() : `${data?.summary.numeric_columns.length ?? 0} numeric`
                  }
                  icon={<ArrowUpRight size={17} />}
                  foot={data?.summary.supports_lead_decisions ? "Scored from five evidence factors" : `${data?.summary.categorical_columns.length ?? 0} categorical columns`}
                  accent
                />
                <Metric
                  label={data?.summary.supports_lead_decisions ? "Potential revenue" : data?.summary.primary_metric ?? "Numeric total"}
                  value={
                    data?.summary.supports_lead_decisions ? compactMoney(data.summary.potential_revenue) : data?.summary.primary_metric_sum == null ? "—" : data.summary.primary_metric_sum.toLocaleString("en-IN", { maximumFractionDigits: 2 })
                  }
                  icon={<Activity size={17} />}
                  foot={data?.summary.supports_lead_decisions ? "High-priority opportunity value" : `Sum of ${data?.summary.primary_metric ?? "numeric values"}`}
                />
                <Metric
                  label="Decisions generated"
                  value={decision ? "1" : "0"}
                  icon={<GitBranch size={17} />}
                  foot="This prototype session"
                />
                <Metric
                  label="Decision time"
                  value="< 3 min"
                  icon={<Clock3 size={17} />}
                  foot="Target vs. ~15 min manual"
                />
              </div>
              <div className="dashboard-grid">
                <section className="panel chart-panel">
                  <PanelTitle
                    title={data?.summary.supports_lead_decisions ? "Lead priority distribution" : `Top ${data?.summary.categorical_columns[0] ?? "category values"}`}
                    detail={data?.summary.supports_lead_decisions ? "Scored records · active dataset" : "Counts from the active dataset"}
                  />
                  <div className="priority-chart">
                    <ResponsiveContainer width="100%" height={205}>
                      <PieChart>
                        <Pie
                          data={distribution}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={58}
                          outerRadius={82}
                          paddingAngle={4}
                          stroke="none"
                        >
                          {distribution.map((entry, index) => (
                            <Cell key={entry.name} fill={chartColors[index]} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{
                            background: "#1d1f21",
                            border: "1px solid #36383a",
                            borderRadius: 5,
                            color: "#f2efe8",
                          }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="donut-center">
                      <strong>{data?.summary.rows ?? 0}</strong>
                      <span>{data?.summary.supports_lead_decisions ? "LEADS" : "ROWS"}</span>
                    </div>
                  </div>
                  <div className="legend">
                    {distribution.map((item, index) => (
                      <div key={item.name}>
                        <span style={{ background: chartColors[index] }} />
                        {item.name}
                        <strong>{item.value}</strong>
                      </div>
                    ))}
                  </div>
                </section>
                <section className="panel chart-panel revenue-panel">
                  <PanelTitle
                    title={data?.summary.supports_lead_decisions ? "Revenue opportunity" : `${data?.summary.primary_metric ?? "Numeric"} trend`}
                    detail={data?.summary.supports_lead_decisions ? "Lead value by last contact month" : `By ${data?.summary.date_columns[0] ?? "date"} · active dataset`}
                  />
                  <div className="chart-total">
                    {data?.summary.supports_lead_decisions ? money(data.summary.potential_revenue) : data?.summary.primary_metric_sum?.toLocaleString("en-IN") ?? "—"}{" "}
                    <span>{data?.summary.supports_lead_decisions ? "high-priority pool" : `total ${data?.summary.primary_metric ?? "metric"}`}</span>
                  </div>
                  <ResponsiveContainer width="100%" height={216}>
                    <AreaChart
                      data={data?.summary.revenue_opportunity ?? []}
                      margin={{ top: 8, right: 5, left: -18, bottom: 0 }}
                    >
                      <defs>
                        <linearGradient
                          id="revFill"
                          x1="0"
                          y1="0"
                          x2="0"
                          y2="1"
                        >
                          <stop
                            offset="0%"
                            stopColor="#d6a14b"
                            stopOpacity={0.25}
                          />
                          <stop
                            offset="95%"
                            stopColor="#d6a14b"
                            stopOpacity={0}
                          />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#2b2d2e" vertical={false} />
                      <XAxis
                        dataKey="month"
                        tick={{ fill: "#7f8284", fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fill: "#7f8284", fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        tickFormatter={(value: number) => data?.summary.supports_lead_decisions ? `${Math.round(value / 100000)}L` : value.toLocaleString("en-IN")}
                      />
                      <Tooltip
                        formatter={(value) => data?.summary.supports_lead_decisions ? money(Number(value)) : Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                        contentStyle={{
                          background: "#1d1f21",
                          border: "1px solid #36383a",
                          borderRadius: 5,
                        }}
                      />
                      <Area
                        type="monotone"
                        dataKey="value"
                        stroke="#d6a14b"
                        strokeWidth={2}
                        fill="url(#revFill)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </section>
                <section className="panel recent-panel">
                  <PanelTitle
                    title="Recent decisions"
                    detail="This session"
                    action={
                      <button
                        className="panel-link"
                        onClick={() => setView("decisions")}
                      >
                        View all <ArrowRight size={13} />
                      </button>
                    }
                  />
                  {decision ? (
                    decision.leads.slice(0, 3).map((lead) => (
                      <RecentDecision
                        key={lead.lead_id}
                        lead={lead}
                        onClick={() => {
                          setActiveLead(lead);
                          setView("evidence");
                        }}
                      />
                    ))
                  ) : (
                    <EmptyInline
                      title="No decisions yet"
                      detail="Start with a question about your sales data."
                      button="Ask DecisionOS"
                      onClick={() => setView("ask")}
                    />
                  )}
                </section>
                <section className="panel activity-panel">
                  <PanelTitle
                    title="Decision activity"
                    detail="Workflow trace"
                  />
                  <div className="activity-list">
                    <ActivityRow
                      icon={<Database size={14} />}
                      title="Business data connected"
                      detail={`${data?.summary.rows ?? 0} records · ${data?.summary.data_quality ?? 0}% quality`}
                    />
                    <ActivityRow
                      icon={<Sparkles size={14} />}
                      title="Analysis ready"
                      detail={
                        decision
                          ? new Date(decision.created_at).toLocaleTimeString(
                              [],
                              { hour: "2-digit", minute: "2-digit" },
                            )
                          : "Awaiting first question"
                      }
                    />
                    <ActivityRow
                      icon={<FileCheck2 size={14} />}
                      title="Evidence attached"
                      detail={
                        decision
                          ? `${decision.evidence.length} source records traced`
                          : "No evidence generated"
                      }
                    />
                    <ActivityRow
                      icon={<ShieldCheck size={14} />}
                      title="Human review"
                      detail={
                        approvalState
                          ? `Decision ${approvalState}`
                          : "Approval required before action"
                      }
                      last
                    />
                  </div>
                </section>
              </div>
              <div className="disclaimer">
                <ShieldCheck size={14} /> DecisionOS recommends. A human
                decides. Metrics shown are prototype/demo values unless sourced
                from your loaded dataset.
              </div>
            </>
          )}

          {view === "data" && (
            <>
              <PageHeading
                eyebrow="CONNECTED SOURCES / 01"
                title="Business Data"
                subtitle="Upload CSV or Excel files to profile and analyze your business data."
              />
              <div className="data-actions">
                <label
                  className={`upload-zone ${dragActive ? "drag-active" : ""}`}
                  onDragOver={(event) => { event.preventDefault(); setDragActive(true); }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragActive(false);
                    upload(event.dataTransfer.files[0]);
                  }}
                >
                  <input
                    type="file"
                    accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                    onChange={(event) => upload(event.target.files?.[0])}
                  />
                  <Upload size={22} />
                  <strong>UPLOAD YOUR BUSINESS DATA</strong>
                  <span>Drag and drop or click to upload CSV or Excel files.</span>
                  <span className="upload-formats">CSV • XLSX • XLS</span>
                  {dragActive && <span className="drop-prompt">Drop to upload</span>}
                </label>
                {uploadSteps.length > 0 && (
                  <div className="upload-steps">
                    {["✓ File uploaded", "✓ Dataset parsed", "✓ Data analyzed", "✓ Ready for questions"].map((step) => (
                      <span key={step} className={uploadSteps.includes(step) ? "step-done" : "step-pending"}>
                        {uploadSteps.includes(step) ? step : step.replace("✓", "…").replace(" for questions", "")}
                      </span>
                    ))}
                  </div>
                )}
                <div className="data-source">
                  <div className="source-icon">
                    <Database size={20} />
                  </div>
                  <div>
                    <span className="eyebrow">ACTIVE DATASET</span>
                    <strong>{data?.summary.filename ?? "No dataset"}</strong>
<<<<<<< HEAD
                    <small>{data?.summary.source === "demo" ? "● Demo dataset" : data?.summary.source === "upload" ? "● Uploaded dataset" : "No dataset loaded"}{data?.summary.file_type ? ` · ${data.summary.file_type.toUpperCase()}` : ""}</small>
                  </div>
                  {data?.summary.dataset_id && (
                    <button
                      className="secondary-button"
                      onClick={deleteActiveDataset}
                      disabled={busy}
                    >
                      Delete dataset <X size={14} />
                    </button>
                  )}
=======
                    <small>{data?.summary.source === "demo" ? "● Demo dataset" : "● Uploaded dataset"} · {data?.summary.file_type?.toUpperCase()}</small>
                  </div>
>>>>>>> 8e03c96660b8785c021372d016b8b39ca7766d71
                  <button
                    className="secondary-button"
                    onClick={loadDemo}
                    disabled={busy}
                  >
                    Load demo data <ArrowRight size={14} />
                  </button>
                </div>
              </div>
              {data?.summary.sheet_names && data.summary.sheet_names.length > 1 && (
                <label className="sheet-select-row">
                  <span>Select workbook sheet</span>
                  <select value={data.summary.selected_sheet ?? data.summary.sheet_names[0]} onChange={(event) => changeSheet(event.target.value)}>
                    {data.summary.sheet_names.map((sheet) => <option key={sheet}>{sheet}</option>)}
                  </select>
                </label>
              )}
              <div className="data-stats">
                {[
                  ["Rows", data?.summary.rows ?? "—"],
                  ["Columns", data?.summary.columns ?? "—"],
                  ["Missing values", data?.summary.missing_values ?? "—"],
                  ["Duplicates", data?.summary.duplicates ?? "—"],
                  ["Data quality", data ? `${data.summary.data_quality}%` : "—"],
                  ["Numeric columns", data?.summary.numeric_columns.length ?? "—"],
                  ["Categorical columns", data?.summary.categorical_columns.length ?? "—"],
                  ["Date columns", data?.summary.date_columns.length ?? "—"],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              {(data?.summary.quality_warnings.length || data?.summary.preprocessing.length) ? (
                <section className="quality-notes panel">
                  <strong>DATA QUALITY & PREPROCESSING</strong>
                  {[...(data?.summary.quality_warnings ?? []), ...(data?.summary.preprocessing ?? [])].map((item) => <span key={item}>{item}</span>)}
                </section>
              ) : null}
              <section className="panel table-panel profile-panel">
                <PanelTitle title="Dataset profile" detail={`${data?.summary.column_profiles.length ?? 0} columns · statistics calculated from active data`} />
                <div className="table-scroll"><table><thead><tr>{["Column", "Type", "Missing", "Missing %", "Unique", "Top values", "Min", "Max", "Mean", "Median", "Sum", "Std. dev."].map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{(data?.summary.column_profiles ?? []).map((profile) => <tr key={profile.name}><td><strong>{profile.name}</strong></td><td>{profile.dtype}</td><td>{profile.missing}</td><td>{profile.missing_percentage}%</td><td>{profile.unique}</td><td>{profile.top_values?.map(({ value, count }) => `${String(value)} (${count})`).join(" · ") ?? "—"}</td><td>{profile.min ?? "—"}</td><td>{profile.max ?? "—"}</td><td>{profile.mean ?? "—"}</td><td>{profile.median ?? "—"}</td><td>{profile.sum ?? "—"}</td><td>{profile.std ?? "—"}</td></tr>)}</tbody></table></div>
              </section>
              {(data?.summary.numeric_correlations.length ?? 0) > 0 && (
                <section className="panel table-panel">
                  <PanelTitle title="Numeric correlations" detail="Pearson correlation · pairs with at least 3 complete rows" />
                  <div className="table-scroll"><table><thead><tr>{["Column A", "Column B", "Correlation", "Paired rows"].map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{data?.summary.numeric_correlations.map((pair) => <tr key={`${pair.column_a}-${pair.column_b}`}><td><strong>{pair.column_a}</strong></td><td>{pair.column_b}</td><td>{pair.correlation.toFixed(3)}</td><td>{pair.paired_rows}</td></tr>)}</tbody></table></div>
                </section>
              )}
              <section className="panel table-panel">
                <PanelTitle
                  title="Source records"
                  detail={`${data?.preview.length ?? 0} source rows · ${data?.summary.filename ?? "active dataset"}`}
                />
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        {(data?.summary.columns_list ?? []).map((column) => (
                          <th key={column}>{column}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(data?.preview ?? []).map((row, index) => (
                        <tr key={`${index}-${String(row[data?.summary.columns_list[0] ?? ""] ?? "")}`}>
                          {(data?.summary.columns_list ?? []).map((column) => (
                            <td key={column}>{row[column] == null ? <span className="missing">Missing</span> : String(row[column])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {view === "ask" && (
            <>
              <PageHeading
                eyebrow="DECISION ENGINE / 02"
                title="Ask DecisionOS"
                subtitle="Ask a question about your active business data. Every answer is calculated from its actual rows."
              />
              <div className="active-dataset-strip"><Database size={16} /><div><span>ACTIVE DATASET</span><strong>{data?.summary.filename ?? "No dataset connected"}</strong></div><small>{data?.summary.rows?.toLocaleString() ?? 0} rows · {data?.summary.columns ?? 0} columns</small><span className={`dataset-connected ${data ? (data.summary.source === "demo" ? "demo" : "") : "offline"}`}><i />{data?.summary.source === "demo" ? "● DEMO DATASET" : "● UPLOADED DATASET"}</span></div>
              <section className="ask-composer panel">
                <div className="composer-label">
                  <span className="composer-icon">
                    <Sparkles size={16} />
                  </span>
                  <div>
                    <strong>Ask anything about your uploaded business data</strong>
                    <small>
                      Analytics questions are computed by Pandas. Lead actions use the PS-04 decision engine.
                    </small>
                  </div>
                  <span className="deterministic-tag">DATA-GROUNDED ANALYSIS</span>
                </div>
                <label htmlFor="decision-question" className="sr-only">
                  Business question
                </label>
                <textarea
                  id="decision-question"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask anything about your uploaded business data…"
                  rows={4}
                />
                <div className="composer-bottom">
                  <span>
                    <Database size={13} /> {data?.summary.rows ?? 0} records in
                    context
                  </span>
                  <button
                    className="primary-button"
                    disabled={busy || !question.trim()}
                    onClick={analyze}
                  >
                    {busy ? "Analyzing…" : "Analyze"}{" "}
                    <ArrowRight size={15} />
                  </button>
                </div>
              </section>
              <section className="llm-provider panel" aria-label="AI provider settings">
                <div className="llm-provider-copy">
                  <strong>AI provider</strong>
                  <small>Question planning and result explanation</small>
                </div>
                <label>
                  <span className="sr-only">Select AI provider</span>
                  <select
                    value={llmProviderStatus?.active_provider ?? "gemini"}
                    onChange={(event) => changeLLMProvider(event.target.value as LLMProviderName)}
                    disabled={busy || !llmProviderStatus}
                  >
                    {(llmProviderStatus?.providers ?? [
                      { name: "gemini" as const, label: "Gemini", configured: false },
                      { name: "openrouter" as const, label: "OpenRouter", configured: false },
                      { name: "groq" as const, label: "Groq", configured: false },
                    ]).map((provider) => <option key={provider.name} value={provider.name}>{provider.label}</option>)}
                  </select>
                </label>
                <span className={`llm-provider-status ${llmProviderStatus?.active_configured ? "configured" : "unconfigured"}`}>
                  <i />
                  {llmProviderStatus?.active_configured
                    ? "Configured"
                    : `${llmProviderStatus?.providers.find((provider) => provider.name === llmProviderStatus.active_provider)?.label ?? "Gemini"} is not configured. Add ${llmProviderStatus?.active_provider === "groq" ? "GROQ_API_KEY" : llmProviderStatus?.active_provider === "openrouter" ? "OPENROUTER_API_KEY" : "GEMINI_API_KEY"} to backend/.env.`}
                </span>
              </section>
              <div className="suggestion-heading">
                <span>START WITH A QUESTION</span>
                <span>EXAMPLES</span>
              </div>
              <div className="question-list">
                {askSuggestions.map((example, index) => (
                  <button
                    key={example}
                    onClick={() => setQuestion(example)}
                    className={
                      question === example
                        ? "question-chip selected"
                        : "question-chip"
                    }
                  >
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    {example}
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
              <div className="ask-guardrail">
                <ShieldCheck size={17} />
                <div>
                  <strong>Evidence before explanation</strong>
                  <p>
                    Business facts come from your dataset and deterministic
                    scoring. The language model is optional and cannot add or
                    alter source values.
                  </p>
                </div>
              </div>
            </>
          )}

          {view === "analytics" && (
            <>
              <PageHeading
                eyebrow="ACTIVE DATA / PANDAS ANALYSIS"
                title="Analytics Result"
                subtitle={analyticsResult?.question ?? "Ask a question to analyze the active dataset."}
              />
              {analyticsResult ? (
                <>
                  <section className="analytics-answer panel">
                    <div className="analytics-answer-top"><span className="eyebrow">ANSWER · {analyticsResult.filename}</span><span className="dataset-connected"><i />FROM ACTIVE DATASET</span></div>
                    <h2>{analyticsResult.answer}</h2>
                    <p>{analyticsResult.explanation}</p>
                    <div className="analytics-facts"><span>{analyticsResult.rows_analyzed.toLocaleString()} rows analyzed</span><span>{analyticsResult.columns_used.length ? `Columns: ${analyticsResult.columns_used.join(" · ")}` : "All columns"}</span><span>Operation: {analyticsResult.operation}</span></div>
                  </section>
                  <div className="analytics-detail-grid">
                    <section className="panel analytics-chart-panel">
                      <PanelTitle title="Result visualization" detail={analyticsResult.chart ? `${analyticsResult.chart.type} chart · calculated from query results` : "No chart is needed for this answer"} />
                      {analyticsResult.chart ? (
                        <ResponsiveContainer width="100%" height={300}>
                          {analyticsResult.chart.type === "bar" ? (
                            <BarChart data={analyticsResult.chart.data} margin={{ top: 12, right: 12, left: 0, bottom: 8 }}><CartesianGrid stroke="#2b2d2e" vertical={false} /><XAxis dataKey={analyticsResult.chart.x_key} tick={{ fill: "#898c8d", fontSize: 10 }} /><YAxis tick={{ fill: "#898c8d", fontSize: 10 }} /><Tooltip contentStyle={{ background: "#1d1f21", border: "1px solid #36383a", borderRadius: 5 }} /><Bar dataKey={analyticsResult.chart.y_key} fill="#d9a650" radius={[3, 3, 0, 0]} /></BarChart>
                          ) : analyticsResult.chart.type === "line" ? (
                            <LineChart data={analyticsResult.chart.data} margin={{ top: 12, right: 12, left: 0, bottom: 8 }}><CartesianGrid stroke="#2b2d2e" vertical={false} /><XAxis dataKey={analyticsResult.chart.x_key} tick={{ fill: "#898c8d", fontSize: 10 }} /><YAxis tick={{ fill: "#898c8d", fontSize: 10 }} /><Tooltip contentStyle={{ background: "#1d1f21", border: "1px solid #36383a", borderRadius: 5 }} /><Line dataKey={analyticsResult.chart.y_key} stroke="#d9a650" strokeWidth={2} dot={{ fill: "#edbd68", r: 3 }} /></LineChart>
                          ) : (
                            <PieChart><Tooltip contentStyle={{ background: "#1d1f21", border: "1px solid #36383a", borderRadius: 5 }} /><Pie data={analyticsResult.chart.data} dataKey={analyticsResult.chart.y_key} nameKey={analyticsResult.chart.x_key} innerRadius={58} outerRadius={105} paddingAngle={3}>{analyticsResult.chart.data.map((item, index) => <Cell key={`${String(item[analyticsResult.chart!.x_key])}-${index}`} fill={chartColors[index % chartColors.length]} />)}</Pie></PieChart>
                          )}
                        </ResponsiveContainer>
                      ) : <div className="chart-empty"><BarChart3 size={22} /><span>This result is best reviewed as a value or source-row table.</span></div>}
                    </section>
                    <section className="panel calculation-panel"><PanelTitle title="How we calculated it" detail="Validated Pandas operation" />{[["Metric", analyticsResult.calculation.metric ?? "Record count"], ["Operation", analyticsResult.calculation.operation], ["Grouped by", analyticsResult.calculation.group_by ?? "None"], ["Sort", analyticsResult.calculation.sort]].map(([label, value]) => <div className="calculation-row" key={label}><span>{label}</span><strong>{value}</strong></div>)}<div className="calculation-proof"><Check size={15} /> Values returned from the active dataset; no facts supplied by the LLM.</div></section>
                  </div>
                  <section className="panel table-panel analytics-table"><PanelTitle title="Calculated results" detail={`${analyticsResult.result.length} rows · ${analyticsResult.rows_analyzed.toLocaleString()} source rows analyzed`} /><div className="table-scroll"><table><thead><tr>{Object.keys(analyticsResult.result[0] ?? {}).map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{analyticsResult.result.map((row, index) => <tr key={index}>{Object.keys(analyticsResult.result[0] ?? {}).map((column) => <td key={column}>{row[column] == null ? "—" : String(row[column])}</td>)}</tr>)}</tbody></table></div></section>
                  <details className="panel analytics-evidence"><summary><FileCheck2 size={15} /> Source data <span>{analyticsResult.evidence.length} contributing rows shown · click to inspect</span></summary><div className="table-scroll"><table><thead><tr>{Object.keys(analyticsResult.evidence[0] ?? {}).map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{analyticsResult.evidence.map((row, index) => <tr key={index}>{Object.keys(analyticsResult.evidence[0] ?? {}).map((column) => <td key={column}>{row[column] == null ? <span className="missing">Missing</span> : String(row[column])}</td>)}</tr>)}</tbody></table></div></details>
                </>
              ) : <EmptyState icon={<BarChart3 size={22} />} title="No analytics result yet" detail="Ask DecisionOS a question about the connected dataset." button="Ask a question" onClick={() => setView("ask")} />}
            </>
          )}

          {view === "decisions" && (
            <>
              <PageHeading
                eyebrow="RECOMMENDATION / 03"
                title="Decision Results"
                subtitle={
                  decision?.question ??
                  "Run an analysis to generate a ranked recommendation from your data."
                }
              />
              {decision ? (
                <>
                  <section className="recommendation-banner">
                    <div className="recommend-icon">
                      <Sparkles size={19} />
                    </div>
                    <div className="recommend-copy">
                      <span className="eyebrow">RECOMMENDED ACTION</span>
                      <h2>{decision.recommendation}</h2>
                      <p>{decision.expected_impact}</p>
                    </div>
                    <div className="confidence">
                      <span>CONFIDENCE</span>
                      <strong>{decision.confidence}%</strong>
                      <div className="confidence-track">
                        <i style={{ width: `${decision.confidence}%` }} />
                      </div>
                      <small>Prototype rank-margin estimate</small>
                    </div>
                  </section>
                  <p className="decision-explanation">{decision.explanation}</p>
                  <div className="result-toolbar">
                    <div>
                      <strong>{decision.leads.length} leads ranked</strong>
                      <span>
                        {" "}
                        · transparent five-factor score · sorted highest first
                      </span>
                    </div>
                    <button
                      className="secondary-button"
                      onClick={() => setView("evidence")}
                    >
                      <FileText size={14} /> View evidence
                    </button>
                  </div>
                  <section className="panel table-panel">
                    <div className="table-scroll">
                      <table className="decision-table">
                        <thead>
                          <tr>
                            <th>Rank</th>
                            <th>Lead</th>
                            <th>Priority</th>
                            <th>Score</th>
                            <th>Potential revenue</th>
                            <th>Evidence summary</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {decision.leads.map((lead, index) => (
                            <tr key={lead.lead_id}>
                              <td className="rank-cell">
                                {String(index + 1).padStart(2, "0")}
                              </td>
                              <td>
                                <strong>{lead.company}</strong>
                                <small>
                                  {lead.lead_id} ·{" "}
                                  {lead.industry ?? "Industry n/a"}
                                </small>
                              </td>
                              <td>
                                <span
                                  className={`priority-badge ${lead.priority.toLowerCase()}`}
                                >
                                  <i />
                                  {lead.priority}
                                </span>
                              </td>
                              <td>
                                <span className="score-cell">{lead.score}</span>
                              </td>
                              <td>{money(lead.lead_value)}</td>
                              <td className="reason-cell">{lead.reason}</td>
                              <td>
                                <button
                                  className="row-action"
                                  onClick={() => {
                                    setActiveLead(lead);
                                    setView("evidence");
                                  }}
                                >
                                  Evidence <ArrowRight size={13} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                  <div className="trace-caption">
                    <GitBranch size={14} /> {decision.trace.length} trace steps
                    · Created {new Date(decision.created_at).toLocaleString()}
                  </div>
                  <DecisionContext decision={decision} filename={data?.summary.filename ?? "Active dataset"} status={approvalState} />
                </>
              ) : (
                <DecisionStatePanel state={decisionLoadState} error={decisionLoadError} icon={<Search size={22} />} onAsk={() => setView("ask")} onRetry={() => void loadCurrentDecision(data?.summary.dataset_id, false, true)} />
              )}
            </>
          )}

          {view === "evidence" && (
            <>
              <PageHeading
                eyebrow="DECISION TRACE / 04"
                title="Evidence & Trace"
                subtitle="Every recommendation is connected to source records and visible scoring factors."
              />
              {decision && <DecisionContext decision={decision} filename={data?.summary.filename ?? "Active dataset"} status={approvalState} />}
              {decision ? (
                <div className="evidence-layout">
                  <section className="panel evidence-main">
                    <div className="evidence-select">
                      <div>
                        <span className="eyebrow">WHY THIS DECISION?</span>
                        <h2>Lead evidence</h2>
                      </div>
                      <label className="select-wrap">
                        <span className="sr-only">Choose lead</span>
                        <select
                          value={
                            activeLead?.lead_id ?? decision.leads[0]?.lead_id
                          }
                          onChange={(event) =>
                            setActiveLead(
                              decision.leads.find(
                                (lead) => lead.lead_id === event.target.value,
                              ) ?? null,
                            )
                          }
                        >
                          {decision.leads.map((lead) => (
                            <option key={lead.lead_id} value={lead.lead_id}>
                              {lead.company} · {lead.score}
                            </option>
                          ))}
                        </select>
                        <ChevronDown size={14} />
                      </label>
                    </div>
                    {activeLead && (
                      <>
                        <div className="evidence-lead-title">
                          <div className="company-monogram">
                            {activeLead.company.slice(0, 1)}
                          </div>
                          <div>
                            <h3>{activeLead.company}</h3>
                            <span>
                              {activeLead.lead_id} ·{" "}
                              {activeLead.industry ?? "Industry n/a"}
                            </span>
                          </div>
                          <span
                            className={`priority-badge ${activeLead.priority.toLowerCase()}`}
                          >
                            <i />
                            {activeLead.priority} PRIORITY
                          </span>
                        </div>
                        <div className="evidence-grid">
                          {[
                            ["Lead value", money(activeLead.lead_value)],
                            ["Decision score", activeLead.score],
                            [
                              "Engagement",
                              activeLead.engagement_score == null
                                ? "Missing"
                                : `${activeLead.engagement_score}/100`,
                            ],
                            [
                              "Previous purchases",
                              activeLead.previous_purchases ?? "Missing",
                            ],
                            [
                              "Last contact date",
                              activeLead.last_contact_date ?? "Missing",
                            ],
                            [
                              "Recent activity",
                              activeLead.days_since_contact == null
                                ? "Unknown"
                                : `${activeLead.days_since_contact} days ago`,
                            ],
                            [
                              "Lead status",
                              activeLead.lead_status ?? "Missing",
                            ],
                            [
                              "Last activity",
                              activeLead.sales_activity ?? "Missing",
                            ],
                          ].map(([label, value]) => (
                            <div key={label}>
                              <span>{label}</span>
                              <strong>{value}</strong>
                              <small>Source: loaded business dataset</small>
                            </div>
                          ))}
                        </div>
                        <div className="factor-section">
                          <div className="factor-heading">
                            <strong>Priority score breakdown</strong>
                            <span>
                              Weighted contributions · total {activeLead.score}
                            </span>
                          </div>
                          {Object.entries(activeLead.contributions).map(
                            ([key, value]) => (
                              <div className="factor-row" key={key}>
                                <span>{factorLabels[key] ?? key}</span>
                                <div className="factor-meter">
                                  <i
                                    style={{
                                      width: `${Math.min(100, value * 3)}%`,
                                    }}
                                  />
                                </div>
                                <strong>+{Math.round(value)}</strong>
                              </div>
                            ),
                          )}
                        </div>
                        <div className="equation">
                          <span>REVENUE</span>
                          <b>+</b>
                          <span>ENGAGEMENT</span>
                          <b>+</b>
                          <span>RECENCY</span>
                          <b>+</b>
                          <span>PURCHASES</span>
                          <b>+</b>
                          <span>STATUS</span>
                          <ArrowRight size={14} />
                          <strong>{activeLead.score} SCORE</strong>
                        </div>
                      </>
                    )}
                  </section>
                  <aside className="panel trace-panel">
                    <PanelTitle title="Decision trace" detail={decision.trace_details?.scoring_method ?? "Source-to-recommendation path"} />
                    <div className="trace-metadata">
                      <span>Dataset · {decision.trace_details?.dataset_filename ?? data?.summary.filename ?? "Active dataset"}</span>
                      <span>Dataset ID · {decision.dataset_id}</span>
                      <span>Records · {decision.trace_details?.records_considered ?? decision.retrieved_record_ids?.length ?? decision.leads.length} considered / {decision.trace_details?.records_ranked ?? decision.leads.length} ranked</span>
                      <span>Evidence · {decision.trace_details?.evidence_records ?? decision.evidence.length} records</span>
                      <span>Weights · {Object.entries(decision.weights).map(([factor, value]) => `${factor} ${Math.round(value * 100)}%`).join(" · ")}</span>
                    </div>
                    {decision.trace.map((step, index) => (
                      <div className="trace-step" key={step}>
                        <span>
                          {index === decision.trace.length - 1 ? (
                            <Check size={13} />
                          ) : (
                            String(index + 1).padStart(2, "0")
                          )}
                        </span>
                        <div>
                          <strong>{step}</strong>
                          {index === 1 && <small>{decision.trace_details?.dataset_filename ?? data?.summary.filename ?? "Active dataset"} · {decision.dataset_id}</small>}
                        </div>
                      </div>
                    ))}
                    <div className="trace-result">
                      <BadgeCheck size={16} />
                      <span>Recommendation grounded in retrieved records</span>
                    </div>
                  </aside>
                </div>
              ) : (
                <DecisionStatePanel state={decisionLoadState} error={decisionLoadError} icon={<FileCheck2 size={22} />} onAsk={() => setView("ask")} onRetry={() => void loadCurrentDecision(data?.summary.dataset_id, false, true)} />
              )}
            </>
          )}

          {view === "simulator" && (
            <>
              <PageHeading
                eyebrow="SCENARIO PLANNING / 05"
                title="What-If Decision Simulator"
                subtitle="Change the assumptions. See how the recommendation changes."
              />
              {decision && <DecisionContext decision={decision} filename={data?.summary.filename ?? "Active dataset"} status={approvalState} />}
              {decision ? (
                <>
                  <section className="panel simulator-controls">
                    <div className="simulator-head">
                      <div>
                        <span className="eyebrow">ADJUST SCORING WEIGHTS</span>
                        <h2>What matters most right now?</h2>
                      </div>
                      <span className="weight-total">
                        {Object.values(weights).reduce(
                          (sum, value) => sum + value,
                          0,
                        )}
                        % TOTAL
                      </span>
                    </div>
                    <div className="slider-grid">
                      {Object.entries(factorLabels).map(([key, label]) => (
                        <label className="weight-control" key={key}>
                          <span>
                            <strong>{label}</strong>
                            <output>{weights[key]}%</output>
                          </span>
                          <input
                            type="range"
                            min="0"
                            max="100"
                            value={weights[key]}
                            onChange={(event) =>
                              setWeights(
                                rebalanceWeights(
                                  weights,
                                  key,
                                  Number(event.target.value),
                                ),
                              )
                            }
                            aria-label={label}
                          />
                          <small>
                            {key === "revenue"
                              ? "Prioritize larger opportunities"
                              : key === "engagement"
                                ? "Prioritize active interest"
                                : key === "recency"
                                  ? "Prioritize recent conversations"
                                  : key === "purchases"
                                    ? "Reward proven buying history"
                                    : "Factor in current lead status"}
                          </small>
                        </label>
                      ))}
                    </div>
                    <div className="simulator-run">
                      <span>
                        Weights are normalized by the decision engine before
                        recalculation.
                      </span>
                      <button
                        className="primary-button"
                        onClick={simulate}
                        disabled={busy}
                      >
                        {busy ? "Recalculating…" : "Run simulation"}{" "}
                        <Play size={14} />
                      </button>
                    </div>
                  </section>
                  <div className="ranking-compare">
                    <Ranking
                      title="Current ranking"
                      leads={
                        simulation?.current_ranking ??
                        decision.leads.slice(0, 5)
                      }
                    />
                    <div className="compare-mark">
                      <ArrowRight size={20} />
                    </div>
                    <Ranking
                      title="Simulated ranking"
                      leads={simulation?.simulated_ranking ?? []}
                      empty={!simulation}
                    />
                  </div>
                  {simulation && (
                    <div className="simulation-result">
                      <div className="change-mark">
                        <ArrowDownRight size={18} />
                      </div>
                      <div>
                        <strong>{simulation.changed_positions ? `${simulation.changed_positions} ranking positions changed` : "Ranking unchanged under these assumptions."}</strong>
                        <p>{simulation.explanation}</p>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <DecisionStatePanel state={decisionLoadState} error={decisionLoadError} icon={<SlidersHorizontal size={22} />} onAsk={() => setView("ask")} onRetry={() => void loadCurrentDecision(data?.summary.dataset_id, false, true)} />
              )}
            </>
          )}

          {view === "approval" && (
            <>
              <PageHeading
                eyebrow="HUMAN-IN-THE-LOOP / 06"
                title="Human Approval"
                subtitle="AI recommends. Human decides."
              />
              {decision && <DecisionContext decision={decision} filename={data?.summary.filename ?? "Active dataset"} status={approvalState} />}
              {decision ? (
                <div className="approval-layout">
                  <section className="panel approval-card">
                    <div className="approval-top">
                      <span className="eyebrow">{approvalState === "pending" ? "PENDING DECISION" : "DECISION REVIEWED"}</span>
                      <span
                        className={`approval-state ${approvalState || "pending"}`}
                      >
                        <i />
                        {approvalState
                          ? approvalState.toUpperCase()
                          : "AWAITING REVIEW"}
                      </span>
                    </div>
                    <h2>{approval?.action === "modify" ? approval.recommendation : decision.recommendation}</h2>
                    <p className="approval-evidence">
                      {decision.leads[0]?.company}: {decision.leads[0]?.reason}.{" "}
                      {decision.expected_impact}
                    </p>
                    <div className="approval-proof">
                      <div>
                        <span>CONFIDENCE</span>
                        <strong>{decision.confidence}%</strong>
                      </div>
                      <div>
                        <span>TOP LEAD</span>
                        <strong>{decision.leads[0]?.company ?? "—"}</strong>
                      </div>
                      <div>
                        <span>EXPECTED VALUE</span>
                        <strong>{money(decision.leads[0]?.lead_value)}</strong>
                      </div>
                    </div>
                    <label className="form-label">
                      Modify recommendation
                      <textarea
                        rows={3}
                        value={modifiedRecommendation}
                        onChange={(event) =>
                          setModifiedRecommendation(event.target.value)
                        }
                      />
                    </label>
                    <label className="form-label">
                      Review note / rejection reason
                      <textarea
                        rows={2}
                        value={approvalNote}
                        onChange={(event) =>
                          setApprovalNote(event.target.value)
                        }
                        placeholder="Required when rejecting; optional otherwise"
                      />
                    </label>
                    <div className="approval-actions">
                      <button
                        className="approve-button"
                        disabled={busy || approvalState === "approved"}
                        onClick={() => sendApproval("approve")}
                      >
                        <Check size={15} /> Approve
                      </button>
                      <button
                        className="modify-button"
                        disabled={busy}
                        onClick={() => sendApproval("modify")}
                      >
                        Modify
                      </button>
                      <button
                        className="reject-button"
                        disabled={busy || approvalState === "rejected"}
                        onClick={() => sendApproval("reject")}
                      >
                        <X size={15} /> Reject
                      </button>
                    </div>
                    {approval && (
                      <div className="approval-history">
                        <strong>REVIEW HISTORY</strong>
                        <span>Decision ID · {approval.decision_id}</span>
                        <span>Action · {approval.action.toUpperCase()}</span>
                        {approval.recommendation && <span>Recommendation · {approval.recommendation}</span>}
                        {approval.note && <span>Note · {approval.note}</span>}
                        <span>Recorded · {new Date(approval.timestamp).toLocaleString()}</span>
                        <small>Human approval recorded. No external action was executed.</small>
                      </div>
                    )}
                  </section>
                  <aside className="approval-aside">
                    <div className="human-statement">
                      <ShieldCheck size={21} />
                      <span>THE FINAL CALL</span>
                      <strong>
                        AI recommends.
                        <br />
                        You decide.
                      </strong>
                      <p>No action is executed without human approval.</p>
                    </div>
                    <div className="approval-check">
                      <Check size={15} />
                      <span>Recommendation generated</span>
                    </div>
                    <div className="approval-check">
                      <Check size={15} />
                      <span>Evidence attached</span>
                    </div>
                    <div className="approval-check">
                      <Check size={15} />
                      <span>{approvalState === "pending" ? "Human approval required" : "Human approval recorded"}</span>
                    </div>
                  </aside>
                </div>
              ) : (
                <DecisionStatePanel state={decisionLoadState} error={decisionLoadError} icon={<ShieldCheck size={22} />} onAsk={() => setView("ask")} onRetry={() => void loadCurrentDecision(data?.summary.dataset_id, false, true)} />
              )}
            </>
          )}

          {view === "evaluation" && (
            <>
              <PageHeading
                eyebrow="QUALITY & RELIABILITY / 07"
                title="Evaluation & Performance"
                subtitle="Prototype test cases and clearly labeled demo metrics. No unmeasured results presented as fact."
              />
              <div className="evaluation-notice">
                <CircleHelp size={17} />
                <div>
                  <strong>
                    {evaluation?.label ??
                      "Prototype demo metrics; not measured production results"}
                  </strong>
                  <span>
                    Replace demo metrics with recorded evaluation runs before
                    making performance claims.
                  </span>
                </div>
              </div>
              <div className="evaluation-metrics">
                {Object.entries(evaluation?.metrics ?? {}).map(
                  ([label, value]) => (
                    <div className="panel eval-metric" key={label}>
                      <span>{label.replaceAll("_", " ")}</span>
                      <strong>{value}</strong>
                      <small>Prototype label</small>
                    </div>
                  ),
                )}
              </div>
              <section className="panel evaluation-baseline">
                <div>
                  <span className="eyebrow">TIME-TO-DECISION</span>
                  <strong>
                    ~{evaluation?.baseline_minutes ?? 15} <small>min</small>
                  </strong>
                  <span>Manual analysis baseline</span>
                </div>
                <ArrowRight size={20} />
                <div>
                  <span className="eyebrow">TARGET</span>
                  <strong>
                    &lt;{evaluation?.target_minutes ?? 3} <small>min</small>
                  </strong>
                  <span>DecisionOS task target</span>
                </div>
                <small className="baseline-note">
                  Target only · not measured result
                </small>
              </section>
              <section className="panel table-panel evaluation-table">
                <PanelTitle
                  title="Evaluation cases"
                  detail={`${evaluation?.cases.length ?? 0} defined behavior checks`}
                />
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Test case</th>
                        <th>Expected decision</th>
                        <th>System behavior</th>
                        <th>Evidence match</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(evaluation?.cases ?? []).map((row, index) => (
                        <tr key={`${row.test_case}-${index}`}>
                          <td>
                            <strong>{row.test_case}</strong>
                          </td>
                          <td>{row.expected_decision}</td>
                          <td>{row.system_decision}</td>
                          <td>{row.evidence_match}</td>
                          <td>
                            <span className="case-status">
                              <i />
                              {row.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function Metric({
  label,
  value,
  icon,
  foot,
  accent = false,
}: {
  label: string;
  value: string;
  icon: ReactNode;
  foot: string;
  accent?: boolean;
}) {
  return (
    <section className={`metric-card ${accent ? "metric-accent" : ""}`}>
      <div className="metric-top">
        <span>{label}</span>
        <i>{icon}</i>
      </div>
      <strong>{value}</strong>
      <small>{foot}</small>
    </section>
  );
}
function PanelTitle({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="panel-title">
      <div>
        <h2>{title}</h2>
        <span>{detail}</span>
      </div>
      {action}
    </div>
  );
}
function RecentDecision({
  lead,
  onClick,
}: {
  lead: Lead;
  onClick: () => void;
}) {
  return (
    <button className="recent-row" onClick={onClick}>
      <span className="recent-monogram">{lead.company.slice(0, 1)}</span>
      <span className="recent-company">
        <strong>{lead.company}</strong>
        <small>{lead.lead_id}</small>
      </span>
      <span className={`priority-badge ${lead.priority.toLowerCase()}`}>
        <i />
        {lead.priority}
      </span>
      <strong className="recent-value">{money(lead.lead_value)}</strong>
      <ArrowRight size={14} />
    </button>
  );
}
function ActivityRow({
  icon,
  title,
  detail,
  last = false,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  last?: boolean;
}) {
  return (
    <div className={`activity-row ${last ? "last" : ""}`}>
      <span className="activity-icon">{icon}</span>
      <div>
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}
function EmptyInline({
  title,
  detail,
  button,
  onClick,
}: {
  title: string;
  detail: string;
  button: string;
  onClick: () => void;
}) {
  return (
    <div className="empty-inline">
      <FileText size={18} />
      <strong>{title}</strong>
      <span>{detail}</span>
      <button onClick={onClick}>
        {button} <ArrowRight size={13} />
      </button>
    </div>
  );
}
function EmptyState({
  icon,
  title,
  detail,
  button,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  button: string;
  onClick: () => void;
}) {
  return (
    <section className="panel empty-state">
      <span className="empty-icon">{icon}</span>
      <h2>{title}</h2>
      <p>{detail}</p>
      <button className="primary-button" onClick={onClick}>
        {button} <ArrowRight size={15} />
      </button>
    </section>
  );
}

function DecisionStatePanel({
  state,
  error,
  icon,
  onAsk,
  onRetry,
}: {
  state: DecisionLoadState;
  error: string;
  icon: ReactNode;
  onAsk: () => void;
  onRetry: () => void;
}) {
  if (state === "loading") {
    return (
      <section className="panel empty-state" role="status">
        <span className="empty-icon">{icon}</span>
        <h2>Loading current decision...</h2>
        <p>Restoring the current recommendation and its approval status.</p>
      </section>
    );
  }
  if (state === "none") {
    return <EmptyState icon={icon} title="No decision available. Run an analysis first." detail="Ask a lead prioritization question to create a ranked, evidence-backed recommendation." button="Ask DecisionOS" onClick={onAsk} />;
  }
  return <EmptyState icon={icon} title={state === "stale" ? "Decision belongs to a different dataset" : "Decision could not be loaded"} detail={error || "Check the backend connection and retry restoring the decision."} button={state === "stale" ? "Ask DecisionOS" : "Retry"} onClick={state === "stale" ? onAsk : onRetry} />;
}

function Ranking({
  title,
  leads,
  empty = false,
}: {
  title: string;
  leads: Lead[];
  empty?: boolean;
}) {
  return (
    <section className="panel ranking-panel">
      <PanelTitle
        title={title}
        detail={empty ? "Run a scenario to compare" : `${leads.length} shown`}
      />
      {empty ? (
        <div className="ranking-empty">
          <SlidersHorizontal size={18} />
          <span>Adjusted ranking will appear here</span>
        </div>
      ) : (
        leads.slice(0, 5).map((lead, index) => (
          <div className="ranking-row" key={lead.lead_id}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{lead.company}</strong>
            <div className="ranking-score">
              <i style={{ width: `${lead.score}%` }} />
              <span>{lead.score}</span>
            </div>
          </div>
        ))
      )}
    </section>
  );
}

export default App;
