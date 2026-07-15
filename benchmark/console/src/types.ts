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
  scope?: "formal_dev" | "regression";
  paper_ids?: string[];
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
  scope: "formal_dev" | "regression";
  paper_ids: string[];
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
  scope?: "formal_dev" | "regression";
  paper_ids?: string[];
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
  scope: "formal_dev" | "regression" | "legacy";
  papers: string[];
  paper_statuses: Record<string, string>;
  paper_diagnostics: Record<string, PaperDiagnostic>;
  usage_totals: Record<string, number>;
  downstream_usage_totals: Record<string, number>;
  shared_roster_bundles: SharedRosterBundle[];
  trace_precision: "exact" | "legacy_synthesized";
  read_only: boolean;
  controllable: boolean;
  resumable: boolean;
  sealed: boolean;
  retryable_papers: string[];
}

export interface PaperDiagnostic {
  paper_id: string;
  status: string;
  stage: string;
  error_type: string;
  error_message: string;
  validator_error_count: number;
  warning_count: number;
  warning_details_available?: boolean;
  historical_warning_count_only?: boolean;
  validator_groups?: ValidatorGroup[];
  transport_error?: TransportError | null;
  roster_bundle_id?: string;
  roster_cache_hit?: boolean;
  report_available: boolean;
  retry_eligible: boolean;
  retry_reason: string;
}

export interface PaperReport {
  status?: string;
  error?: string;
  stage_log?: Record<string, unknown>[];
  validator_errors?: unknown[];
  validator_warnings?: unknown[];
  validator_warnings_count?: number;
  validator_findings?: unknown[];
  validator_groups?: ValidatorGroup[];
  warnings?: unknown[];
  usage_totals?: Record<string, number>;
  downstream_usage?: Record<string, number>;
  shared_roster_usage?: Record<string, number>;
  roster_bundle_id?: string;
  roster_cache_hit?: boolean;
  transport_error?: TransportError | null;
  [key: string]: unknown;
}

export interface ValidatorGroup {
  severity: "error" | "warning" | string;
  root_key: string;
  count: number;
  rule_ids: string[];
  paths: string[];
  messages: string[];
}

export interface TransportError {
  category?: string;
  http_status?: number | null;
  automatic_retryable?: boolean;
  manual_retry_eligible?: boolean;
  provider_request_id?: string;
  response_body_excerpt?: string;
  stage?: string;
  call_id?: string;
}

export interface SharedRosterBundle {
  bundle_id: string;
  paper_ids: string[];
  usage_totals: Record<string, number>;
  cache_hit: boolean;
}

export interface PaperDetail {
  diagnostic: PaperDiagnostic;
  report: PaperReport | null;
  events: TraceEvent[];
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
