// Anthropic §5 HTTP model client — grounded answers over the native Messages
// API (SPEC-PORTS-v1). Anthropic is not OpenAI-shaped, so it gets its own client:
// POST {base}/v1/messages, `system` as a TOP-LEVEL field, a REQUIRED max_tokens,
// and a content[] response whose text blocks are concatenated in order.
//
// Like every §5 client the HTTP call goes through an injected transport, headers
// are ALWAYS just {"Content-Type":"application/json"} (auth is the endpoint
// layer's job), and temperature is always sent (default 0.0 — deterministic).

import { SYSTEM_PROMPT, userMessage, type Transport } from "./openai.js";

/** Anthropic requires max_tokens; use a sane default when the caller gives none. */
const DEFAULT_MAX_TOKENS = 1024;

const JSON_HEADERS: Record<string, string> = { "Content-Type": "application/json" };

export interface AnthropicConfig {
  /** Defaults to Anthropic's public API base. */
  base_url?: string;
  model: string;
  temperature?: number;
  /** Required by the API; defaults to 1024. */
  max_tokens?: number;
}

/** Grounded answers over Anthropic's native `/v1/messages` endpoint. */
export class AnthropicGenerator {
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly temperature: number;
  private readonly maxTokens: number;
  private readonly transport: Transport;

  constructor(config: AnthropicConfig, transport: Transport) {
    this.baseUrl = (config.base_url ?? "https://api.anthropic.com").replace(/\/+$/, "");
    this.model = config.model;
    this.temperature = config.temperature ?? 0.0;
    this.maxTokens = config.max_tokens ?? DEFAULT_MAX_TOKENS;
    this.transport = transport;
  }

  answer(question: string, passage: string, answerLanguage = "en"): string {
    const request: Record<string, unknown> = {
      model: this.model,
      system: SYSTEM_PROMPT,
      messages: [
        { role: "user", content: userMessage(question, passage, answerLanguage) },
      ],
      // max_tokens is required; temperature keeps answers deterministic (§5).
      max_tokens: this.maxTokens,
      temperature: this.temperature,
    };
    const raw = this.transport(
      `${this.baseUrl}/v1/messages`,
      JSON.stringify(request),
      { ...JSON_HEADERS },
    );
    const payload = JSON.parse(raw) as {
      content?: { type?: string; text?: string }[];
    };
    const blocks = payload.content ?? [];
    return blocks
      .filter((block) => block.type === "text")
      .map((block) => block.text ?? "")
      .join("");
  }
}
