// OpenAI-compatible §5 embeddings client (SPEC-PORTS-v1). Posts
// {model, input: texts} to {base}/embeddings and parses data[].embedding into
// dense float vectors, input order preserved.
//
// Like every §5 client the HTTP call goes through an injected transport, and
// headers are ALWAYS just {"Content-Type":"application/json"} — no key/secret
// ever touches a header or the request body.

import type { EmbeddingProvider } from "../contracts.js";
import { wireHeaders } from "../http.js";
import type { Transport } from "./openai.js";

export interface OpenAIEmbedConfig {
  base_url: string;
  model: string;
  /** First-class auth/provider headers as ${ENV} templates (expanded by the
   *  transport at call time, never held as a value). */
  headers?: Record<string, string>;
}

/** Dense embeddings over an OpenAI-compatible `/embeddings` endpoint. */
export class OpenAIEmbedder {
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly transport: Transport;
  private readonly headers: Record<string, string> | undefined;

  constructor(config: OpenAIEmbedConfig, transport: Transport) {
    this.baseUrl = config.base_url.replace(/\/+$/, "");
    this.model = config.model;
    this.transport = transport;
    this.headers = config.headers;
  }

  /** Embed `texts` into dense vectors, preserving input order. Rejects when the
   *  model call fails — the seam's way of saying "I did not embed this"
   *  (ADR-0014 R2). It never returns a placeholder vector. */
  async embed(texts: readonly string[]): Promise<number[][]> {
    const request = { model: this.model, input: [...texts] };
    const raw = await this.transport(
      `${this.baseUrl}/embeddings`,
      JSON.stringify(request),
      wireHeaders(this.headers),
    );
    const payload = JSON.parse(raw) as { data: { embedding: number[] }[] };
    return payload.data.map((item) => item.embedding.map((x) => Number(x)));
  }

  /** Embed a single text — the ingest convenience. Plugs straight into
   *  `ingest()`'s Embedder seam: `(t) => client.embedQuery(t)`. */
  async embedQuery(text: string): Promise<number[]> {
    const first = (await this.embed([text]))[0];
    if (first === undefined) throw new Error("openai embed: empty data");
    return first;
  }
}

// CONTRACT DECLARATION (ADR-0014 R4). Python declares by inheriting the Protocol,
// so `mypy --strict` re-checks the client on every run; TS has structural typing,
// so the idiomatic equivalent is this static assertion — if `OpenAIEmbedder` ever
// drifts from the published seam, `tsc --noEmit` fails HERE rather than a caller
// failing at runtime.
//
// Note what the contract does NOT mention: base_url, headers, transport. Those
// are constructor parameters of this client (R3), which is precisely why an
// in-process provider that never opens a socket satisfies the same interface.
const _embeddingContract: EmbeddingProvider = null! as OpenAIEmbedder;
void _embeddingContract;
