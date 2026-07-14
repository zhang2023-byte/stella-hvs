import type {
  Bootstrap,
  EvaluationState,
  ExperimentGroup,
  GroupPreflight,
  GroupRequest,
  RunSummary,
  Scorecard,
} from "./types";

let sessionToken = "";

export function setSessionToken(token: string) {
  sessionToken = token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") {
    headers.set("Content-Type", "application/json");
    headers.set("X-Stella-Console-Token", sessionToken);
  }
  const response = await fetch(path, { ...init, headers });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  return payload as T;
}

export const api = {
  bootstrap: () => request<Bootstrap>("/api/bootstrap"),
  preflightGroup: (payload: GroupRequest) =>
    request<GroupPreflight>("/api/experiment-groups/preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createGroup: (payload: GroupRequest) =>
    request<ExperimentGroup>("/api/experiment-groups", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  groups: async () => (await request<{ groups: ExperimentGroup[] }>("/api/experiment-groups")).groups,
  group: (groupId: string) => request<ExperimentGroup>(`/api/experiment-groups/${encodeURIComponent(groupId)}`),
  stopGroup: (groupId: string) =>
    request<ExperimentGroup>(`/api/experiment-groups/${encodeURIComponent(groupId)}/stop`, {
      method: "POST",
      body: "{}",
    }),
  resumeGroup: (groupId: string) =>
    request<ExperimentGroup>(`/api/experiment-groups/${encodeURIComponent(groupId)}/resume`, {
      method: "POST",
      body: "{}",
    }),
  runs: async () => (await request<{ runs: RunSummary[] }>("/api/runs")).runs,
  run: (campaignId: string, runId: string) =>
    request<RunSummary>(`/api/runs/${encodeURIComponent(campaignId)}/${encodeURIComponent(runId)}`),
  blob: (campaignId: string, runId: string, digest: string) =>
    request<{ kind: string; payload: unknown }>(`/api/runs/${encodeURIComponent(campaignId)}/${encodeURIComponent(runId)}/blobs/${digest}`),
  resetRun: (runId: string) =>
    request<{ run_id: string; status: string; removed: string[] }>(`/api/runs/${encodeURIComponent(runId)}/reset`, {
      method: "POST",
      body: JSON.stringify({ confirm_run_id: runId }),
    }),
  evaluationPreflight: (groupId: string, runIds: string[], allowUnavailable: boolean) =>
    request<{ ok: boolean; checks: { name: string; ok: boolean; detail: string }[] }>(
      `/api/experiment-groups/${encodeURIComponent(groupId)}/evaluation/preflight`,
      { method: "POST", body: JSON.stringify({ run_ids: runIds, allow_unavailable: allowUnavailable }) },
    ),
  startEvaluation: (groupId: string, runIds: string[], allowUnavailable: boolean) =>
    request<EvaluationState>(`/api/experiment-groups/${encodeURIComponent(groupId)}/evaluation`, {
      method: "POST",
      body: JSON.stringify({ run_ids: runIds, allow_unavailable: allowUnavailable }),
    }),
  evaluation: (groupId: string) => request<EvaluationState>(`/api/experiment-groups/${encodeURIComponent(groupId)}/evaluation`),
  scorecards: async (groupId: string) =>
    (await request<{ scorecards: Scorecard[] }>(`/api/experiment-groups/${encodeURIComponent(groupId)}/scorecards`)).scorecards,
};
