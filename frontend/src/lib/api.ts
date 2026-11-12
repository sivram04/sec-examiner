// Typed client for the FastAPI backend (src/research_desk/api.py).
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8011";

export type Company = { ticker: string; documents: number; latest_filing: string };
export type Hit = {
  id: string; ticker: string; form: string; filed: string; section: string;
  section_title: string; text: string; url: string; score: number;
};
export type Trace = { agent: string; secs: number; [k: string]: unknown };
export type Verdict = { claim: { text: string; citations: string[]; stance: string }; ok: boolean; reasons: string[] };
export type DeskResponse =
  | { thread: string; status: "needs_input"; interrupt: { type: string; plan?: unknown; flagged?: unknown }; trace: Trace[] }
  | { thread: string; status: "done"; report: string; trace: Trace[]; verdicts: Verdict[] };
export type RiskChange = {
  added: { risk: string; evidence: string; filing: string; since: string }[];
  removed: { risk: string; filing: string; until: string }[];
};
export type FactPoint = { end: string; value: number; filed: string; accession: string };
export type ReportRow = { id: number; ticker: string; question: string; as_of: string; created: number };

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
  companies: () => call<Company[]>("/api/companies"),
  search: (p: Record<string, string>) => call<{ ms: number; hits: Hit[] }>(`/api/search?${new URLSearchParams(p)}`),
  risks: (t: string, start: string, end: string) =>
    call<RiskChange>(`/api/risks/${encodeURIComponent(t)}?start=${start}&end=${end}`),
  facts: (t: string, concept: string) => call<FactPoint[]>(`/api/facts/${encodeURIComponent(t)}/${concept}`),
  reports: () => call<ReportRow[]>("/api/reports"),
  report: (id: number) => call<{ ticker: string; question: string; as_of: string; report: string }>(`/api/reports/${id}`),
  research: (body: { ticker: string; question: string; as_of: string }) =>
    call<DeskResponse>("/api/research", { method: "POST", body: JSON.stringify(body) }),
  resume: (thread: string, answer: unknown) =>
    call<DeskResponse>(`/api/research/${encodeURIComponent(thread)}/resume`, { method: "POST", body: JSON.stringify(answer) }),
};

export const today = () => new Date().toISOString().slice(0, 10);
export const yearAgo = () => new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
