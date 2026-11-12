// Typed client for the FastAPI backend (src/research_desk/api.py).
// In the deployed build NEXT_PUBLIC_API_URL is "" (same origin); in development the API runs on 8011.
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8011";

export type Prediction = {
  topic: string; label: string; about: string; score: number;
  from_filing: number; from_history: number; missing: string[];
};
export type ExamResult = {
  model: string;
  note: string | null;
  words: number;
  cached?: boolean;
  filing: { company: string; form: string; filed: string; period: string | null; url: string; sic: string };
  predictions: Prediction[];
  others: { topic: string; label: string; score: number }[];
  past_letters: { date: string; topics: string[]; comments: number }[];
  sections_read: string[];
  secs: number;
};
export type Attempt = {
  time: string | null; version: string; parent: string | null; changes: Record<string, unknown>;
  rationale: string; selection_f1: number | null; holdout_f1: number | null;
  decision: string; reason: string;
};
type Window = { f1: number | null; n: number | null; baselines: Record<string, number> };
export type LoopStatus = {
  champion: string | null; lineage: string[]; judge_sealed: boolean;
  selection: Window; holdout: Window; trained_on: number | null; train_window: string[] | null;
  topic_recall: { topic: string; label: string; n: number; recall: number }[];
  attempts: Attempt[];
};

export type Quota = { limited: boolean; limit: number; used: number; remaining: number | null; resets: string; help: string };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail ?? r.statusText);
  return body as T;
}

export const api = {
  examineTicker: (t: string) => call<ExamResult>(`/api/examiner/ticker/${encodeURIComponent(t)}`),
  examineDraft: (body: { text: string; sic?: string; form?: string }) =>
    call<ExamResult>("/api/examiner/draft", { method: "POST", body: JSON.stringify(body) }),
  loopStatus: () => call<LoopStatus>("/api/examiner/status"),
  quota: () => call<Quota>("/api/examiner/quota"),
};
