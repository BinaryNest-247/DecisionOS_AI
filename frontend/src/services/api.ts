import type { AnalyticsResult, Approval, DataResponse, Decision, DecisionEvidenceResponse, DecisionLatestResponse, LLMProviderName, LLMProviderStatus, SimulationResult } from "../types";

const API_ROOT = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  summary: () => request<DataResponse>("/api/data/summary"),
  profile: () => request<DataResponse["summary"]>("/api/data/profile"),
  llmProviders: () => request<LLMProviderStatus>("/api/llm/providers"),
  selectLLMProvider: (provider: LLMProviderName) => request<LLMProviderStatus>("/api/llm/provider", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider }),
  }),
  loadDemo: () =>
    request<{ summary: DataResponse["summary"] }>("/api/data/demo", {
      method: "POST",
    }),
  upload: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ filename: string; summary: DataResponse["summary"]; preview: DataResponse["preview"] }>("/api/data/upload", {
      method: "POST",
      body: form,
    });
  },
  selectSheet: (sheetName: string) => request<DataResponse>("/api/data/select-sheet", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sheet_name: sheetName }),
  }),
  deleteDataset: (datasetId: string) => request<{ status: "deleted"; dataset_id: string }>(`/api/dataset/${encodeURIComponent(datasetId)}`, {
    method: "DELETE",
  }),
  analytics: (question: string) => request<AnalyticsResult>("/api/analytics/query", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
  }),
  analyze: (question: string) =>
    request<Decision>("/api/decision/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, limit: 10 }),
    }),
  getDecision: (decisionId: string) => request<Decision>(`/api/decision/${encodeURIComponent(decisionId)}`),
  latestDecision: async (): Promise<DecisionLatestResponse | null> => {
    try {
      return await request<DecisionLatestResponse>("/api/decision/latest");
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },
  getEvidence: (decisionId: string) => request<DecisionEvidenceResponse>(`/api/decision/${encodeURIComponent(decisionId)}/evidence`),
  getApproval: (decisionId: string) => request<{ decision_id: string; approval: Approval | null }>(`/api/decision/${encodeURIComponent(decisionId)}/approval`),
  simulate: (decisionId: string, weights: Record<string, number>) =>
    request<SimulationResult>("/api/simulation/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision_id: decisionId, weights }),
    }),
  approve: (payload: {
    decision_id: string;
    action: string;
    note?: string;
    modified_recommendation?: string;
  }) =>
    request<{ status: "recorded"; approval: Approval }>("/api/approval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  evaluation: () =>
    request<{
      label: string;
      metrics: Record<string, string>;
      baseline_minutes: number;
      target_minutes: number;
      cases: Array<Record<string, string>>;
    }>("/api/evaluation"),
};
