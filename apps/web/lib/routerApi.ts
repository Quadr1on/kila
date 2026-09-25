// Cascade router API (kila/router/api.py).

import { api } from "./api";

export type QuestionResult = {
  choice: string;
  conf: number;
  raw_choice: string;
  raw_conf: number;
  entropy_conf: number;
  probs: Record<string, number>;
};

export type RouteDecision = {
  ok: boolean;
  error?: string;
  task_type: string | null;
  task_conf?: number;
  difficulty?: string;
  difficulty_conf?: number;
  needs_vision?: boolean;
  vision_source?: string | null;
  perception?: string | null;
  retrieval_relevance?: number | null;
  alpha?: number;
  tau?: number;
  score?: number;
  base_role?: string;
  chosen_role: string;
  chosen_model: string;
  escalated: boolean;
  escalation_reasons?: string[];
  escalation_blocked?: string | null;
  summary: string;
  latency_ms: number;
  classifier?: { classifier: string; checkpoint: string; device: string; language: string | null; latency_ms: number };
  questions?: Record<string, QuestionResult>;
  task_id?: string | null;
  classifier_ms?: number | null;
};

export type RouterStats = {
  decisions: number;
  escalated: number;
  escalation_rate: number | null;
  below_tau: number;
  by_model: Record<string, number>;
  by_task_type: Record<string, number>;
  latency_ms: { p50: number; p95: number; mean: number } | null;
};

export type DecisionRow = {
  task_id: string;
  created_at: string;
  status: string;
  task_type: string;
  task_conf: number;
  difficulty: string;
  retrieval_relevance: number;
  score: number;
  tau: number;
  alpha: number;
  chosen_model: string;
  escalated: boolean;
  latency_ms: number;
};

type Eval = { n: number; accuracy: number; ece: number; mean_conf: number; nll: number };
type SweepPoint = { tau: number; escalation_rate: number; kept_accuracy: number | null; hard_escalated: number | null };

export type Calibration = {
  ts: string;
  labels: number;
  fit: number;
  test: number;
  questions: Record<string, { temperature: number; before: Eval; after: Eval; laya_entropy_conf_ece: number }>;
  task_type_accuracy_by_language: Record<string, { accuracy: number; n: number }>;
  task_type_top_confusions: [string, number][];
  tau_sweep: { target_kept_accuracy: number; chosen_tau: number; test: SweepPoint[]; chosen_on_test: SweepPoint };
  alpha: { value: number; tuned: boolean; note: string };
  laya_latency_ms: { device: string; p50: number; p95: number; by_checkpoint_p50: Record<string, number> };
};

export type RouterConfig = {
  cascade: { alpha: number; tau: number; [k: string]: unknown };
  calibration: Record<string, number>;
  questions: Record<string, string[]>;
  classifier: { loaded: boolean; name: string | null; device: string | null; load_ms: number | null };
};

export const routerApi = {
  preview: (text: string, attachment_kinds: string[], retrieval_relevance: number | null) =>
    api<RouteDecision>("/router/route", {
      method: "POST",
      body: JSON.stringify({ text, attachment_kinds, retrieval_relevance }),
    }),
  stats: () => api<RouterStats>("/router/stats"),
  decisions: (limit = 30) => api<DecisionRow[]>(`/router/decisions?limit=${limit}`),
  calibration: () => api<Calibration>("/router/calibration"),
  config: () => api<RouterConfig>("/router/config"),
};

export const TASK_LABEL: Record<string, string> = {
  approval_note: "Approval note",
  inspection_summary: "Inspection summary",
  engineering_calc: "Engineering calc",
  pid_digitise: "P&ID digitise",
  code_task: "Code",
  correspondence: "Correspondence",
  sheet_analysis: "Sheet analysis",
  general_qa: "General Q&A",
};
