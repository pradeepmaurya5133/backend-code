/**
 * Subh AI API client, shared by the web, mobile and desktop front ends.
 *
 * Deliberately dependency-free (plain fetch) so the same file can be imported
 * by Vite, Expo and Tauri without a bundler-specific shim.
 */

const DEFAULT_BASE = "http://127.0.0.1:8000";

export class SubhApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "SubhApiError";
    this.status = status;
    this.body = body;
  }
}

export function createClient({ baseUrl = DEFAULT_BASE, getToken = () => null } = {}) {
  async function request(path, { method = "GET", body, query } = {}) {
    const url = new URL(baseUrl + path);
    if (query) {
      Object.entries(query).forEach(([key, value]) => {
        if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
      });
    }

    const headers = { "Content-Type": "application/json" };
    const token = getToken();
    // Either credential works; a raw API key is handy for scripts, a JWT for browsers.
    if (token) {
      if (token.startsWith("subh_")) headers["X-API-Key"] = token;
      else headers.Authorization = `Bearer ${token}`;
    }

    let response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (cause) {
      throw new SubhApiError(
        `Cannot reach Subh AI at ${baseUrl}. Is the backend running?`,
        0,
        { cause: String(cause) }
      );
    }

    const text = await response.text();
    let parsed = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { raw: text };
    }

    if (!response.ok) {
      const detail = parsed?.detail || parsed?.message || response.statusText;
      throw new SubhApiError(
        typeof detail === "string" ? detail : `Request failed (${response.status})`,
        response.status,
        parsed
      );
    }
    return parsed;
  }

  return {
    request,

    // --- system ---
    health: () => request("/api/health"),
    root: () => request("/"),
    metrics: () => request("/api/metrics"),
    preflight: () => request("/api/preflight"),

    // --- agent ---
    status: () => request("/api/agent/status"),
    run: (message, sessionId, plan = true) =>
      request("/api/agent/run", { method: "POST", body: { message, session_id: sessionId, plan } }),
    resume: (sessionId) =>
      request("/api/agent/resume", { method: "POST", body: { session_id: sessionId } }),
    pending: (sessionId) => request("/api/agent/pending", { query: { session_id: sessionId } }),
    transcript: (sessionId) => request("/api/agent/transcript", { query: { session_id: sessionId } }),
    sessions: () => request("/api/agent/sessions"),
    reset: (sessionId) =>
      request("/api/agent/reset", { method: "POST", body: { session_id: sessionId } }),

    // --- voice ---
    voiceStatus: () => request("/api/voice/status"),
    voiceTurn: (transcript, sessionId) =>
      request("/api/voice/turn", { method: "POST", body: { transcript, session_id: sessionId } }),

    // --- tools and permissions ---
    tools: () => request("/api/tools"),
    executeTool: (tool, args, sessionId) =>
      request("/api/tools/execute", {
        method: "POST",
        body: { tool, arguments: args, session_id: sessionId },
      }),
    permissions: () => request("/api/permissions"),
    grant: (permission) =>
      request("/api/permissions/grant", { method: "POST", body: { permission } }),
    revoke: (permission) =>
      request("/api/permissions/revoke", { method: "POST", body: { permission } }),

    // --- approvals ---
    confirmations: () => request("/api/confirmations"),
    approve: (token) => request("/api/confirmations/approve", { method: "POST", body: { token } }),
    deny: (token) => request("/api/confirmations/deny", { method: "POST", body: { token } }),

    // --- memory ---
    memory: (sessionId, kind) => request("/api/memory", { query: { session_id: sessionId, kind } }),
    remember: (content, sessionId, kind = "fact", importance = 0.6) =>
      request("/api/memory", {
        method: "POST",
        body: { content, session_id: sessionId, kind, importance },
      }),
    forget: (id) => request(`/api/memory/${id}`, { method: "DELETE" }),

    // --- automation ---
    tasks: () => request("/api/tasks"),
    createTask: (task) => request("/api/tasks", { method: "POST", body: task }),
    runTask: (id) => request(`/api/tasks/${id}/run`, { method: "POST" }),
    enableTask: (id) => request(`/api/tasks/${id}/enable`, { method: "POST" }),
    disableTask: (id) => request(`/api/tasks/${id}/disable`, { method: "POST" }),
    deleteTask: (id) => request(`/api/tasks/${id}`, { method: "DELETE" }),

    // --- audit ---
    audit: (limit = 50) => request("/api/audit", { query: { limit } }),

    // --- auth ---
    authStatus: () => request("/api/auth/status"),
    exchangeToken: (apiKey) =>
      request("/api/auth/token", { method: "POST", body: { api_key: apiKey } }),
  };
}

export default createClient;
