/** Normalize an API error into a renderable string.
 *
 * FastAPI validation failures (422) put a LIST of pydantic error objects
 * ({type, loc, msg, input}) in `detail`. Storing that array in error state and
 * rendering `{error}` throws React error #31 ("objects are not valid as a React
 * child") and blanks the entire page — which is exactly what happened when
 * auto-propose 422'd. Every setError(...detail...) site must go through this
 * so no backend response shape can ever crash the tree.
 */
export function errorText(e: unknown, fallback: string): string {
  const status = (e as { response?: { status?: number } })?.response?.status;

  // ADR-317 D4 — a 401 renders as FastAPI's stock "Not authenticated", which is
  // accurate and useless to a captain in a van: it names the state, not the
  // action. It also reads like a permissions problem, and during the incident
  // that produced this it was mistaken for one (a role rejection is a 403 and
  // says "Operation not permitted").
  //
  // Deliberately client-side: the server's message is correct, and other
  // consumers may reasonably render it differently.
  if (status === 401) return 'Your session expired — sign in again.';

  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
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
