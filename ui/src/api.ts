const BASE = "http://localhost:8000";

export async function chatTask(task: string): Promise<{
  session_id: string;
  mode: "direct" | "align" | "clarify" | "confirm_dangerous";
  questions?: { key: string; q: string }[];
  question?: string;
  triggers?: string[];
}> {
  const r = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
  });
  return r.json();
}

export async function submitTask(task: string) {
  const r = await fetch(`${BASE}/task/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
  });
  return r.json();
}

export async function approveTask(sessionId: string, spec: Record<string, string>) {
  const r = await fetch(`${BASE}/task/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, spec }),
  });
  return r.json();
}

export async function deliverTask(sessionId: string, accepted: boolean, feedback = "") {
  const r = await fetch(`${BASE}/task/deliver`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, accepted, feedback }),
  });
  return r.json();
}

export async function getCost(): Promise<{ total_usd: number; calls: number }> {
  const r = await fetch(`${BASE}/cost`);
  return r.json();
}

export function openWs(sessionId: string, onMsg: (e: { event: string; data: unknown }) => void): WebSocket {
  const ws = new WebSocket(`ws://localhost:8000/ws/${sessionId}`);
  ws.onmessage = (e) => onMsg(JSON.parse(e.data));
  return ws;
}

export async function getSettings(): Promise<AppSettings> {
  const r = await fetch(`${BASE}/settings`);
  return r.json();
}

export async function saveSettings(s: AppSettings): Promise<void> {
  await fetch(`${BASE}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
}

export async function listModels(): Promise<string[]> {
  const r = await fetch(`${BASE}/models`);
  const j = await r.json();
  return j.models ?? [];
}

export interface McpServer { name: string; url: string; enabled: boolean; }
export interface AppSettings {
  maker_model: string;
  checker_model: string;
  checker_fallbacks: string[];
  max_rounds: number;
  temperature: number;
  max_tokens: number;
  system_prompt: string;
  mcp_servers: McpServer[];
  api_keys: Record<string, string>;
}
