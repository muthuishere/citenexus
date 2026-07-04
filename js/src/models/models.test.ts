import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { OpenAIChatGenerator, type Transport } from "./openai.js";
import { AnthropicGenerator } from "./anthropic.js";
import { OpenAIEmbedder } from "./embed.js";

// The §5 HTTP model clients are proven against the shared wire fixture — every
// request BODY (parsed JSON) and every parsed response must match the Python
// reference exactly. Follows the tokenize exemplar: load the fixture, assert over
// ALL cases, no leniency. Transports are FAKES so the suite is hermetic.

type ClientKind = "openai_chat" | "anthropic" | "openai_embed";

interface WireConfig {
  base_url?: string;
  model: string;
  max_tokens?: number;
}

interface ChatInputs {
  question: string;
  passage: string;
  answer_language: string;
}
interface EmbedInputs {
  texts: string[];
}

interface RequestCase {
  name: string;
  client: ClientKind;
  config: WireConfig;
  inputs: ChatInputs | EmbedInputs;
  expected_request: {
    method: string;
    url: string;
    headers: Record<string, string>;
    body: unknown;
  };
}

interface ResponseCase {
  name: string;
  client: ClientKind;
  response_body: unknown;
  expected: unknown;
}

interface WireFixture {
  requests: RequestCase[];
  responses: ResponseCase[];
}

const fixture = loadCase<WireFixture>("model_wire.json");

/** A transport that records the one call made through it. */
function capturingTransport(): {
  transport: Transport;
  calls: { url: string; body: string; headers: Record<string, string> }[];
} {
  const calls: { url: string; body: string; headers: Record<string, string> }[] = [];
  const transport: Transport = (url, body, headers) => {
    calls.push({ url, body, headers });
    return "{}";
  };
  return { transport, calls };
}

/** A transport that returns a fixed, canned response. */
function cannedTransport(response: unknown): Transport {
  return () => JSON.stringify(response);
}

/** Invoke the client named by `kind` with the fixture inputs. */
function invoke(kind: ClientKind, config: WireConfig, inputs: ChatInputs | EmbedInputs, transport: Transport): unknown {
  if (kind === "openai_chat") {
    const c = inputs as ChatInputs;
    return new OpenAIChatGenerator(
      { base_url: config.base_url ?? "", model: config.model, max_tokens: config.max_tokens ?? null },
      transport,
    ).answer(c.question, c.passage, c.answer_language);
  }
  if (kind === "anthropic") {
    const c = inputs as ChatInputs;
    return new AnthropicGenerator(
      { base_url: config.base_url, model: config.model, max_tokens: config.max_tokens },
      transport,
    ).answer(c.question, c.passage, c.answer_language);
  }
  const e = inputs as EmbedInputs;
  return new OpenAIEmbedder({ base_url: config.base_url ?? "", model: config.model }, transport).embed(e.texts);
}

describe("model wire conformance — requests", () => {
  it("has cases", () => {
    expect(fixture.requests.length).toBeGreaterThan(0);
  });

  for (const c of fixture.requests) {
    it(c.name, () => {
      const { transport, calls } = capturingTransport();
      // The stub response ("{}") makes response parsing throw; we assert only on
      // the captured request, which is recorded before the client parses.
      try {
        invoke(c.client, c.config, c.inputs, transport);
      } catch {
        /* response parse is irrelevant to the request contract */
      }
      expect(calls.length).toBe(1);
      const call = calls[0]!;
      expect({
        method: "POST",
        url: call.url,
        headers: call.headers,
        body: JSON.parse(call.body),
      }).toEqual(c.expected_request);
    });
  }
});

describe("model wire conformance — responses", () => {
  it("has cases", () => {
    expect(fixture.responses.length).toBeGreaterThan(0);
  });

  for (const c of fixture.responses) {
    it(c.name, () => {
      const transport = cannedTransport(c.response_body);
      // Response inputs are irrelevant to the parse; supply harmless placeholders.
      const inputs: ChatInputs | EmbedInputs =
        c.client === "openai_embed"
          ? { texts: ["x"] }
          : { question: "q", passage: "p", answer_language: "en" };
      const out = invoke(c.client, { base_url: "https://api.example.com/v1", model: "m" }, inputs, transport);
      expect(out).toEqual(c.expected);
    });
  }
});
