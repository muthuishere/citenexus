// The shipped clients' CONTRACT DECLARATION, checked in the test suite too.
//
// The real check is the static assertion at the bottom of each client module —
// `tsc --noEmit` fails there if a client drifts from the published shape. This
// file makes the claim visible in `npm test` as well, and exercises it through
// the contract rather than through the concrete class, which is the thing that
// actually matters to a caller.

import { describe, expect, expectTypeOf, it } from "vitest";

import type { EmbeddingProvider, GeneratorProvider } from "../contracts.js";
import { AnthropicGenerator } from "./anthropic.js";
import { OpenAIEmbedder } from "./embed.js";
import { OpenAIChatGenerator, type Transport } from "./openai.js";

describe("the shipped clients satisfy the published contracts", () => {
  it("OpenAIEmbedder is an EmbeddingProvider", () => {
    expectTypeOf<OpenAIEmbedder>().toMatchTypeOf<EmbeddingProvider>();
  });

  it("both generators are one GeneratorProvider", () => {
    // An Anthropic-shaped endpoint and an OpenAI-shaped one are
    // indistinguishable to a caller — the whole point of the contract.
    expectTypeOf<OpenAIChatGenerator>().toMatchTypeOf<GeneratorProvider>();
    expectTypeOf<AnthropicGenerator>().toMatchTypeOf<GeneratorProvider>();
  });

  // R3, checked on a real client: the transport lives in the CONSTRUCTOR, so
  // the contract a provider implements says nothing about HTTP. A provider that
  // never opens a socket satisfies exactly the same interface this client does.
  it("the contract says nothing about the transport", async () => {
    const transport: Transport = () =>
      JSON.stringify({ choices: [{ message: { content: "the passage" } }] });
    const provider: GeneratorProvider = new OpenAIChatGenerator(
      { base_url: "http://example.invalid/v1", model: "qwen" },
      transport,
    );
    expect(await provider.answer("q", "the passage", "en")).toBe("the passage");
  });

  it("the embedding client answers the batch contract, in input order", async () => {
    const transport: Transport = () =>
      JSON.stringify({ data: [{ embedding: [1, 0] }, { embedding: [0, 1] }] });
    const provider: EmbeddingProvider = new OpenAIEmbedder(
      { base_url: "http://example.invalid/v1", model: "bge-m3" },
      transport,
    );
    expect(await provider.embed(["a", "b"])).toEqual([
      [1, 0],
      [0, 1],
    ]);
  });
});
