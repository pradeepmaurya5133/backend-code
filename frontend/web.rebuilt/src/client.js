/**
 * The web client's single API handle.
 *
 * In development VITE_API_BASE is unset, so requests go to this origin and
 * Vite's /api proxy forwards them to the backend - same origin, no CORS. A
 * build that is served separately from the API (the Docker image, Tauri) sets
 * VITE_API_BASE to the API's absolute URL at build time.
 */

import { createClient, SubhApiError } from "@shared/api.js";

const baseUrl = import.meta.env.VITE_API_BASE || window.location.origin;

// A credential is optional: with AUTH_ENABLED=false the API accepts anonymous
// calls. When auth is on, paste an API key or JWT in the System tab.
const TOKEN_KEY = "subh.token";

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private browsing: the in-memory client still works for this session */
  }
}

export const api = createClient({ baseUrl, getToken });
export { SubhApiError, baseUrl };
