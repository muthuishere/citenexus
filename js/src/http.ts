// The shared HTTP layer — the TS port of python citenexus.http.
//
// Auth is a header TEMPLATE: `"Bearer ${API_KEY}"`. The `${ENV_VAR}` is expanded
// from the process environment at the REQUEST BOUNDARY only (toolnexus style), so
// a secret's value never lives on a client object, a config, or a log — only the
// `${NAME}` placeholder does. Model clients hold the template and forward it; the
// transport (here `HttpClient`) resolves it right before the request.

const ENV_RE = /\$\{([A-Za-z0-9_]+)\}/g;
const USER_AGENT = "citenexus";
const DEFAULT_TIMEOUT_MS = 60_000;

/** Expand every `${ENV_VAR}` in `value` from `process.env` (missing → ""). Called
 *  only when a request is sent; the resolved value is used once, never stored. */
export function expandEnv(value: string): string {
  return value.replace(ENV_RE, (_match, name: string) => process.env[name] ?? "");
}

/** `{ "Content-Type": "application/json", ...extra }` — the wire header set a
 *  model client sends. With no extra headers it is exactly the pinned
 *  `model_wire` conformance set. */
export function wireHeaders(extra?: Record<string, string>): Record<string, string> {
  return { "Content-Type": "application/json", ...(extra ?? {}) };
}

/** The default transport: expands `${ENV}` in the final merged headers at call
 *  time. `buildHeaders` stays a pure merge (User-Agent < defaults < per-call);
 *  `resolveHeaders` is the ONLY place a header secret is materialized. */
export class HttpClient {
  private readonly headers: Record<string, string>;
  private readonly timeoutMs: number;

  constructor(headers: Record<string, string> = {}, timeoutMs: number = DEFAULT_TIMEOUT_MS) {
    this.headers = headers;
    this.timeoutMs = timeoutMs;
  }

  /** Merge order: User-Agent < client defaults < per-call (auth wins). Pure —
   *  keeps the `${ENV}` templates unexpanded. */
  buildHeaders(call: Record<string, string>): Record<string, string> {
    return { "User-Agent": USER_AGENT, ...this.headers, ...call };
  }

  /** Merge, then expand `${ENV}` in every value at call time — never stored back. */
  resolveHeaders(call: Record<string, string>): Record<string, string> {
    const merged = this.buildHeaders(call);
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(merged)) out[key] = expandEnv(value);
    return out;
  }

  /** POST `body` to `url` with resolved headers. Async (Node `fetch`), so it is
   *  used where an async transport is accepted; header resolution above is the
   *  reusable, synchronous primitive every transport should apply. */
  async send(url: string, body: string, headers: Record<string, string>): Promise<string> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(url, {
        method: "POST",
        body,
        headers: this.resolveHeaders(headers),
        signal: controller.signal,
      });
      return await response.text();
    } finally {
      clearTimeout(timer);
    }
  }
}
