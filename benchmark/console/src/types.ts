export type Method = "B" | "C";
export type RunStatus =
  | "queued"
  | "resume_queued"
  | "paused"
  | "running"
  | "stop_requested"
  | "stopped"
  | "partial"
  | "failed"
  | "completed"
  | "sealed"
  | "unknown";

export interface RunRequest {
  method: Method;
  run_id: string;
  experiment_name: string;
  extractor_model: string;
  reviewer_model: string;
  task_surface: "full" | "core_prov";
  parallel: number;
  max_repair_rounds: number;
  timeout_seconds: number;
  batch_size: number;
  max_tokens: number | null;
  provider_pin: boolean;
  providers: string[];
  fallback_models: string[];
  stream_responses: boolean;
}

export interface Bootstrap {
  campaign_id: string;
  split: "dev";
  papers: string[];
  models: string[];
  defaults: {
    reviewer_model: string;
    task_surface: "full" | "core_prov";
    parallel: number;
    max_repair_rounds: number;
    timeout_seconds: number;
    batch_size: number;
    provider_pin: boolean;
    max_parallel_experiments: number;
  };
  credentials: { api_key_configured: boolean; base_url_configured: boolean };
  session_token: string;
  capabilities: Record<string, boolean | string>;
}

export interface Check {
  name: string;
  ok: boolean;
  detail: string;
}

export interface ExperimentPreflight {
  run_id: string;
  ok: boolean;
  checks: Check[];
  command: string[];
  request: RunRequest;
}

export interface GroupPreflight {
  ok: boolean;
  group_id: string;
  max_parallel_experiments: number;
  group_checks: Check[];
  experiments: ExperimentPreflight[];
  request: GroupRequest;
}

export interface GroupRequest {
  group_id: string;
  max_parallel_experiments: number;
  experiments: RunRequest[];
}

export interface GroupExperiment {
  run_id: string;
  request: RunRequest;
  status: RunStatus;
  queue_mode: "start" | "resume";
  position: number;
  started_at?: string;
  finished_at?: string;
  error?: string;
}

export interface ExperimentGroup {
  schema: { name: string; version: number };
  group_id: string;
  campaign_id: string;
  split: "dev";
  status: "queued" | "running" | "paused" | "needs_review" | "completed";
  paused: boolean;
  max_parallel_experiments: number;
  created_at: string;
  updated_at: string;
  experiments: GroupExperiment[];
}

export interface RunSummary {
  campaign_id: string;
  run_id: string;
  method: Method | "unknown";
  status: RunStatus;
  created_at: string;
  finished_at: string;
  extractor_model: string;
  reviewer_model: string;
  task_surface: string;
  papers: string[];
  paper_statuses: Record<string, string>;
  usage_totals: Record<string, number>;
  trace_precision: "exact" | "legacy_synthesized";
  read_only: boolean;
  controllable: boolean;
  resumable: boolean;
}

export interface TraceEvent {
  seq: number;
  occurred_at: string;
  campaign_id: string;
  run_id: string;
  method: Method | "unknown";
  type: string;
  paper_id?: string;
  stage?: string;
  status?: string;
  summary?: string;
  data?: Record<string, unknown>;
  payload_ref?: { sha256: string; kind: string; bytes: number };
  usage_delta?: Record<string, number>;
  duration_ms?: number;
  call_id?: string;
  node_id?: string;
  source_node_id?: string;
  target_node_id?: string;
  attempt?: number;
  synthetic?: boolean;
}

export interface EvaluationState {
  schema: { name: string; version: number };
  evaluation_id?: string;
  group_id: string;
  campaign_id: string;
  status: "not_started" | "queued" | "running" | "completed" | "failed";
  run_ids: string[];
  allow_unavailable?: boolean;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  error?: string;
  runs: Record<
    string,
    {
      status: string;
      stage: "audit" | "seal" | "score" | "completed";
      error?: string;
      contaminated_files?: string[];
      hit_count?: number;
      scorecard?: string;
    }
  >;
}

export type Scorecard = Record<string, any>;
