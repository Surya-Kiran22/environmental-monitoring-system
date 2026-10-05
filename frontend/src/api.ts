export const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ? JSON.stringify(j.detail) : msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const get = <T = any>(p: string) => req<T>(p);
export const post = <T = any>(p: string, body?: unknown) => req<T>(p, { method: "POST", body: JSON.stringify(body ?? {}) });
export const put = <T = any>(p: string, body?: unknown) => req<T>(p, { method: "PUT", body: JSON.stringify(body ?? {}) });
export async function upload(p: string, file: File) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API}${p}`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
