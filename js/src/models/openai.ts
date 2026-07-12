// OpenAI-compatible §5 HTTP model clients: a chat generator and an embeddings
// client (SPEC-PORTS-v1). CiteNexus bundles no models — both post plain JSON to
// an injected, OpenAI-shaped endpoint and read the response back.
//
// Every client takes a TRANSPORT — (url, body, headers) -> responseString — so
// tests inject a fake and stay hermetic (no network). Headers are ALWAYS just
// {"Content-Type":"application/json"}: auth is the endpoint layer's job, never
// these clients'. No key/secret ever touches a header or the request body.

/** The single seam every model client posts through. */
export type Transport = (
  url: string,
  body: string,
  headers: Record<string, string>,
) => string;

/** The pinned grounded-answer system prompt (conformance/prompts.json). */
export const SYSTEM_PROMPT =
  "You are a strict, evidence-first assistant. Answer the question by quoting " +
  "the exact sentence or phrase from the provided passage that answers it — " +
  "VERBATIM, word for word, with no rephrasing, no added words, and no " +
  "commentary. If the passage does not contain the answer, say you cannot " +
  "answer from the evidence. The verifier rejects any word not present in the " +
  "passage, so never paraphrase. Quote in the passage's own language when it " +
  "matches the requested ISO code; otherwise still prefer the passage's exact " +
  "wording.";

/** Build the "user" message shared by both generators. */
export function userMessage(question: string, passage: string, answerLanguage: string): string {
  return (
    `Answer language (ISO code): ${answerLanguage}\n\n` +
    `Passage:\n${passage}\n\n` +
    `Question: ${question}`
  );
}

import { wireHeaders } from "../http.js";

export interface OpenAIChatConfig {
  base_url: string;
  model: string;
  /** Always sent on the wire; default 0.0 keeps grounded answers deterministic. */
  temperature?: number;
  /** Sent only when non-null. */
  max_tokens?: number | null;
  /** First-class auth/provider headers as ${ENV} templates, e.g.
   *  `{ Authorization: "Bearer ${OPENAI_API_KEY}" }` — expanded by the transport
   *  at call time, never held as a value. */
  headers?: Record<string, string>;
}

/** Grounded answers over an OpenAI-compatible `/chat/completions` endpoint. */
export class OpenAIChatGenerator {
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly temperature: number;
  private readonly maxTokens: number | null;
  private readonly transport: Transport;
  private readonly headers: Record<string, string> | undefined;

  constructor(config: OpenAIChatConfig, transport: Transport) {
    this.baseUrl = config.base_url.replace(/\/+$/, "");
    this.model = config.model;
    this.temperature = config.temperature ?? 0.0;
    this.maxTokens = config.max_tokens ?? null;
    this.transport = transport;
    this.headers = config.headers;
  }

  answer(question: string, passage: string, answerLanguage = "en"): string {
    const request: Record<string, unknown> = {
      model: this.model,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: userMessage(question, passage, answerLanguage) },
      ],
      // Always sent — a grounded answer must be deterministic (§5).
      temperature: this.temperature,
    };
    if (this.maxTokens !== null) {
      request["max_tokens"] = this.maxTokens;
    }
    const raw = this.transport(
      `${this.baseUrl}/chat/completions`,
      JSON.stringify(request),
      wireHeaders(this.headers),
    );
    const payload = JSON.parse(raw) as {
      choices: { message: { content: string } }[];
    };
    const first = payload.choices[0];
    if (first === undefined) throw new Error("openai chat: empty choices");
    return first.message.content;
  }
}
