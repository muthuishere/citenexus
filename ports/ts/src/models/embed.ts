// OpenAI-compatible §5 embeddings client (SPEC-PORTS-v1). Posts
// {model, input: texts} to {base}/embeddings and parses data[].embedding into
// dense float vectors, input order preserved.
//
// Like every §5 client the HTTP call goes through an injected transport, and
// headers are ALWAYS just {"Content-Type":"application/json"} — no key/secret
// ever touches a header or the request body.

import type { Transport } from "./openai.js";

const JSON_HEADERS: Record<string, string> = { "Content-Type": "application/json" };

export interface OpenAIEmbedConfig {
  base_url: string;
  model: string;
}

/** Dense embeddings over an OpenAI-compatible `/embeddings` endpoint. */
export class OpenAIEmbedder {
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly transport: Transport;

  constructor(config: OpenAIEmbedConfig, transport: Transport) {
    this.baseUrl = config.base_url.replace(/\/+$/, "");
    this.model = config.model;
    this.transport = transport;
  }

  /** Embed `texts` into dense vectors, preserving input order. */
  embed(texts: readonly string[]): number[][] {
    const request = { model: this.model, input: [...texts] };
    const raw = this.transport(
      `${this.baseUrl}/embeddings`,
      JSON.stringify(request),
      { ...JSON_HEADERS },
    );
    const payload = JSON.parse(raw) as { data: { embedding: number[] }[] };
    return payload.data.map((item) => item.embedding.map((x) => Number(x)));
  }

  /** Embed a single text — the ingest convenience. */
  embedQuery(text: string): number[] {
    const first = this.embed([text])[0];
    if (first === undefined) throw new Error("openai embed: empty data");
    return first;
  }
}
