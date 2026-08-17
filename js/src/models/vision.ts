// The injected VL endpoint behind §9 conditional vision.
//
// CiteNexus bundles no models: image description comes from an injected,
// OpenAI-compatible VISION endpoint (Gemini's OpenAI-compat endpoint, GPT-4o, a
// local VL server). Vision is a model like the generator and the embedder, so it
// sits in this module with them, behind the same `Transport` seam and the same
// rule: a key/secret NEVER enters this class — auth is `${ENV}` templates in
// headers, expanded by the transport at the request boundary (`http.ts`).
//
// `describePayload` is exactly the ADR-0005 host-side fulfiller shape, so it
// drops straight into `fulfillVisionRequests`:
//
//     const fulfilled = await fulfillVisionRequests(requests, (url, prompt) =>
//       client.describePayload(url, prompt));
//
// Mirrors `python/src/citenexus/vision/client.py:66` OpenAICompatibleVision.

import { base64Encode } from "../vision/requests.js";
import { wireHeaders } from "../http.js";
import type { Transport } from "./openai.js";

/** The media type `describe` stamps on raw bytes handed to it directly. The
 *  two-phase emit path does NOT use it — `imageDataUri` sniffs the true subtype
 *  from the magic bytes. */
export const DEFAULT_VISION_MIME_TYPE = "image/png";

export interface OpenAIVisionConfig {
  base_url: string;
  model: string;
  /** Always sent on the wire; default 0.0 keeps descriptions deterministic. */
  temperature?: number;
  /** Sent only when non-null. */
  max_tokens?: number | null;
  mime_type?: string;
  /** First-class auth/provider headers as `${ENV}` templates, e.g.
   *  `{ Authorization: "Bearer ${OPENAI_API_KEY}" }` — expanded by the transport
   *  at call time, never held as a value. */
  headers?: Record<string, string>;
}

/** Image description over an OpenAI-compatible vision `/chat/completions`. */
export class OpenAIVision {
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly temperature: number;
  private readonly maxTokens: number | null;
  private readonly mimeType: string;
  private readonly transport: Transport;
  private readonly headers: Record<string, string> | undefined;

  constructor(config: OpenAIVisionConfig, transport: Transport) {
    this.baseUrl = config.base_url.replace(/\/+$/, "");
    this.model = config.model;
    this.temperature = config.temperature ?? 0.0;
    this.maxTokens = config.max_tokens ?? null;
    this.mimeType = config.mime_type ?? DEFAULT_VISION_MIME_TYPE;
    this.transport = transport;
    this.headers = config.headers;
  }

  /** Encode raw image bytes with this client's configured mime type and the
   *  given prompt, then complete. The standalone (non-two-phase) entry. */
  async describe(data: Uint8Array, prompt: string): Promise<Record<string, unknown>> {
    return this.complete(`data:${this.mimeType};base64,${base64Encode(data)}`, prompt);
  }

  /** Fulfil a two-phase PendingVisionRequest: POST the core's already-assembled
   *  `image_url` data URI + prompt VERBATIM (no re-encode), so what goes on the
   *  wire is exactly the emitted payload every port reproduces. */
  async describePayload(imageUrl: string, prompt: string): Promise<Record<string, unknown>> {
    return this.complete(imageUrl, prompt);
  }

  private async complete(imageUrl: string, prompt: string): Promise<Record<string, unknown>> {
    const request: Record<string, unknown> = {
      model: this.model,
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: prompt },
            { type: "image_url", image_url: { url: imageUrl } },
          ],
        },
      ],
      // Always sent — a grounded description must be deterministic (§9).
      temperature: this.temperature,
    };
    if (this.maxTokens !== null) request["max_tokens"] = this.maxTokens;
    const raw = await this.transport(
      `${this.baseUrl}/chat/completions`,
      JSON.stringify(request),
      wireHeaders(this.headers),
    );
    const payload = JSON.parse(raw) as { choices?: { message: { content: string } }[] };
    const first = payload.choices?.[0];
    return parseVisionDescription(first === undefined ? "" : first.message.content);
  }
}

/**
 * Parse a model's reply into a record mapping.
 *
 * A well-behaved model returns JSON; a model that ignores the instruction and
 * returns prose still yields a usable `short_caption` rather than failing — the
 * degrade path, which must never invent structure the model did not produce.
 * Port of `vision/client.py:145` _parse_description, fence handling included.
 */
export function parseVisionDescription(content: string): Record<string, unknown> {
  let text = content.trim();
  if (text.startsWith("```")) {
    // strip a ```json … ``` fence if present
    text = text.replace(/^`+/, "").replace(/`+$/, "");
    if (text.toLowerCase().startsWith("json")) text = text.slice(4);
    text = text.trim();
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { short_caption: content.trim() };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { short_caption: content.trim() };
  }
  return parsed as Record<string, unknown>;
}
