export type Lead = {
  lead_id: string;
  company: string;
  industry?: string | null;
  lead_value: number | null;
  engagement_score: number | null;
  previous_purchases: number | null;
  last_contact_date: string | null;
  days_since_contact: number | null;
  lead_status: string | null;
  sales_activity?: string | null;
  customer_segment?: string | null;
  region?: string | null;
  sales_rep?: string | null;
  score: number;
  priority: "HIGH" | "MEDIUM" | "LOW";
  contributions: Record<string, number>;
  reason: string;
};

export type DecisionTrace = string[];

export type DecisionTraceDetails = {
  dataset_id: string;
  dataset_filename: string;
  records_considered: number;
  records_ranked: number;
  scoring_method: string;
  weights: Record<string, number>;
  evidence_records: number;
};

export type Evidence = {
  lead_id: string;
  company: string;
  source: string;
  fields: {
    lead_value: number | null;
    engagement_score: number | null;
    previous_purchases: number | null;
    last_contact_date: string | null;
    days_since_contact: number | null;
    lead_status: string | null;
  };
  contributions: Record<string, number>;
};

export type ApprovalStatus = "pending" | "approved" | "modified" | "rejected";

export type Approval = {
  decision_id: string;
  action: "approve" | "modify" | "reject";
  note: string;
  recommendation: string | null;
  timestamp: string;
};

export type Decision = {
  id: string;
  dataset_id: string;
  question: string;
  intent: string;
  recommendation: string;
  confidence: number;
  expected_impact: string;
  weights: Record<string, number>;
  retrieved_record_ids?: string[];
  leads: Lead[];
  evidence: Evidence[];
  trace: DecisionTrace;
  trace_details?: DecisionTraceDetails;
  explanation: string;
  created_at: string;
};

export type DecisionLatestResponse = {
  decision: Decision;
  approval: Approval | null;
};

export type DecisionEvidenceResponse = {
  decision_id: string;
  dataset_id: string | null;
  evidence: Evidence[];
  trace: DecisionTrace;
  trace_details: DecisionTraceDetails | Record<string, never>;
};

export type DatasetSummary = {
  dataset_name: string;
  filename: string;
  file_type: string;
  source: "demo" | "upload";
  dataset_id: string;
  sheet_names: string[];
  selected_sheet: string | null;
  rows: number;
  columns: number;
  data_quality: number;
  duplicates: number;
  conflicting_records: number;
  missing_values: number;
  outdated_records: number;
  columns_list: string[];
  priority_distribution: Record<string, number>;
  high_priority_leads: number;
  potential_revenue: number;
  revenue_opportunity: Array<{ month: string; value: number }>;
  column_profiles: Array<{
    name: string;
    dtype: string;
    missing: number;
    missing_percentage: number;
    unique: number;
    top_values?: Array<{ value: string | number | null; count: number }>;
    min?: string | number | null;
    max?: string | number | null;
    mean?: number | null;
    median?: number | null;
    sum?: number | null;
    std?: number | null;
  }>;
  numeric_columns: string[];
  numeric_correlations: Array<{
    column_a: string;
    column_b: string;
    correlation: number;
    paired_rows: number;
  }>;
  categorical_columns: string[];
  date_columns: string[];
  preprocessing: string[];
  quality_warnings: string[];
  supports_lead_decisions: boolean;
  suggested_questions: string[];
  primary_metric: string | null;
  primary_metric_sum: number | null;
  category_distribution: Array<{ name: string; value: number }>;
  missing_percentage: number;
};

export type LLMProviderName = "gemini" | "openrouter" | "groq";

export type LLMProviderStatus = {
  providers: Array<{ name: LLMProviderName; label: string; configured: boolean }>;
  active_provider: LLMProviderName;
  active_configured: boolean;
};

export type DataResponse = {
  summary: DatasetSummary;
  preview: Array<Record<string, string | number | null>>;
};
export type SimulationResult = {
  decision_id: string;
  dataset_id: string;
  current_ranking: Lead[];
  simulated_ranking: Lead[];
  changed_positions: number;
  changed_leads: Array<{ lead_id: string; from_rank: number | null; to_rank: number | null }>;
  weights_before: Record<string, number>;
  weights_after: Record<string, number>;
  explanation: string;
  trace: DecisionTrace;
};

export type AnalyticsResult = {
  question: string;
  answer: string;
  intent: string;
  filename: string;
  columns_used: string[];
  operation: string;
  group_by: string | null;
  calculation: { metric: string | null; operation: string; group_by: string | null; sort: string };
  result: Array<Record<string, string | number | null>>;
  evidence: Array<Record<string, string | number | null>>;
  chart: null | { type: "bar" | "line" | "pie"; x_key: string; y_key: string; data: Array<Record<string, string | number | null>> };
  explanation: string;
  rows_analyzed: number;
  total_rows: number;
  follow_up: boolean;
};
