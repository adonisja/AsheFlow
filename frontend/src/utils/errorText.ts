/** Normalize an API error into a renderable string.
 *
 * FastAPI validation failures (422) put a LIST of pydantic error objects
 * ({type, loc, msg, input}) in `detail`. Storing that array in error state and
 * rendering `{error}` throws React error #31 ("objects are not valid as a React
 * child") and blanks the entire page — which is exactly what happened when
 * auto-propose 422'd. Every setError(...detail...) site must go through this
 * so no backend response shape can ever crash the tree.
 *
 * Network/connectivity failures (no `response`: the request never reached the API
 * or the reply never made it back — a timeout, a dropped connection, or a
 * transient outage that a proxy returns without CORS headers, which the browser
 * then reports as a CORS error) get a single consistent, retryable message
 * instead of the caller's task-specific fallback. "Failed to publish to Discord"
 * is misleading when the truth is "couldn't reach the server".
 */
export function errorText(e: unknown, fallback: string): string {
  const err = e as {
    response?: { data?: { detail?: unknown } };
    code?: string;
    message?: string;
  };

  // No response object → the round-trip didn't complete. Axios sets code
  // 'ERR_NETWORK' (or 'ECONNABORTED' on timeout) and leaves response undefined.
  // Distinct from a real 4xx/5xx, which always carries a response.
  if (!err?.response) {
    if (err?.code === 'ECONNABORTED') {
      return 'The request timed out. Check your connection and try again.';
    }
    if (err?.code === 'ERR_NETWORK' || err?.message === 'Network Error') {
      return "Couldn't reach the server. The action was not completed. Check your connection and try again.";
    }
  }

  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (typeof d === 'string') return d;
      const obj = d as { loc?: unknown[]; msg?: unknown };
      const loc = Array.isArray(obj?.loc)
        ? obj.loc.filter((p) => p !== 'body').join('.')
        : '';
      if (obj?.msg) return loc ? `${loc}: ${String(obj.msg)}` : String(obj.msg);
      try { return JSON.stringify(d); } catch { return String(d); }
    });
    if (parts.length) return parts.join('; ');
  }
  if (detail != null && typeof detail === 'object') {
    try { return JSON.stringify(detail); } catch { /* fall through */ }
  }
  return fallback;
}
