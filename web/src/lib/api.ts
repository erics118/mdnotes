// Typed fetch client. Single-password auth: kept in sessionStorage, prompted on 401,
// sent as Basic (empty user) for fetch and as ?pw= for the PDF iframe.

function pw(): string | null {
  try { return sessionStorage.getItem("mdnotes_pw"); } catch { return null; }
}
function authHeader(): Record<string, string> {
  const p = pw();
  return p ? { Authorization: "Basic " + btoa(":" + p) } : {};
}
export function authHeaders(): Record<string, string> {
  return authHeader();
}
export function pwParam(): string {
  const p = pw();
  return p ? "&pw=" + encodeURIComponent(p) : "";
}
export function encId(id: string): string {
  return encodeURIComponent(id).replace(/%2F/g, "/");
}

async function req(path: string, opts: RequestInit = {}): Promise<Response> {
  let r = await fetch(path, { ...opts, headers: { ...authHeader(), ...(opts.headers || {}) } });
  if (r.status === 401) {
    const p = window.prompt("Password:");
    if (p === null) throw new Error("auth cancelled");
    try { sessionStorage.setItem("mdnotes_pw", p); } catch { /* ignore */ }
    r = await fetch(path, { ...opts, headers: { ...authHeader(), ...(opts.headers || {}) } });
  }
  return r;
}

async function detail(r: Response): Promise<string> {
  try { return (await r.json()).detail || `HTTP ${r.status}`; } catch { return `HTTP ${r.status}`; }
}

export async function get<T>(path: string): Promise<T> {
  const r = await req(path);
  if (!r.ok) throw new Error(await detail(r));
  return r.json() as Promise<T>;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await req(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!r.ok) throw new Error(await detail(r));
  return r.json() as Promise<T>;
}

// ---- types ----
export interface SyncProgress { file: string | null; page: number; pages: number; done: number; }
export interface SyncResult { processed: string[]; skipped: string[]; errors: string[]; stopped: boolean; }
export interface SyncState {
  running: boolean; started: string | null; result: SyncResult | null;
  error: string | null; progress: SyncProgress | null; stopping: boolean;
}
export interface Status {
  authed: boolean; auth_running: boolean; auth_error: string | null;
  folder_name: string | null; folder_id: string | null; folder_configured: boolean;
  output_dir: string; has_anthropic_key: boolean; has_voyage_key: boolean;
  courses: string[]; sync: SyncState;
}
export interface DriveFolder { id: string; name: string; }
export interface SyncFolder { id: string; name: string; path: string; parent_id: string | null; choice: "sync" | "ignore" | "default"; }
export interface NoteMeta { note_id: string; title: string; source_type: string; path: string; page_count: number; }
export interface Hit { note_id: string; title: string; page_num: number; path: string | null; source_type: string; score: number; snippet: string; }
export interface NotePage { page_num: number; total: number; markdown: string; }
