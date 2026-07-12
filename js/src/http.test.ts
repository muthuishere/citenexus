import { afterEach, describe, expect, it } from "vitest";

import { HttpClient, expandEnv, wireHeaders } from "./http.js";
import { OpenAIEmbedder } from "./models/embed.js";

describe("HTTP ${ENV} header auth (toolnexus style)", () => {
  afterEach(() => {
    delete process.env["CN_TEST_KEY"];
  });

  it("expands ${ENV} only at the request boundary, keeping the template pure", () => {
    process.env["CN_TEST_KEY"] = "sk-secret-123";
    const client = new HttpClient();
    const template = { Authorization: "Bearer ${CN_TEST_KEY}" };

    // buildHeaders keeps the template; resolveHeaders (the edge) expands it.
    expect(client.buildHeaders(template)["Authorization"]).toBe("Bearer ${CN_TEST_KEY}");
    expect(client.resolveHeaders(template)["Authorization"]).toBe("Bearer sk-secret-123");
    // The caller's object is never mutated (no value leaks back).
    expect(template.Authorization).toBe("Bearer ${CN_TEST_KEY}");
  });

  it("expands a missing variable to empty", () => {
    delete process.env["CN_ABSENT"];
    expect(expandEnv("Bearer ${CN_ABSENT}")).toBe("Bearer ");
    expect(new HttpClient().resolveHeaders({ X: "${CN_ABSENT}" })["X"]).toBe("");
  });

  it("wireHeaders merges Content-Type with caller header templates", () => {
    expect(wireHeaders()).toEqual({ "Content-Type": "application/json" });
    expect(wireHeaders({ Authorization: "Bearer ${K}" })).toEqual({
      "Content-Type": "application/json",
      Authorization: "Bearer ${K}",
    });
  });

  it("a model client forwards header templates to its transport", () => {
    process.env["CN_TEST_KEY"] = "sk-live-999";
    let seen: Record<string, string> = {};
    const recorder = (_url: string, _body: string, headers: Record<string, string>) => {
      seen = headers;
      return JSON.stringify({ data: [{ embedding: [0.1, 0.2] }] });
    };

    const embedder = new OpenAIEmbedder(
      { base_url: "http://x/v1", model: "m", headers: { Authorization: "Bearer ${CN_TEST_KEY}" } },
      recorder,
    );
    embedder.embed(["hi"]);

    // The client forwards the TEMPLATE; a real HttpClient resolves it at the edge.
    expect(seen["Authorization"]).toBe("Bearer ${CN_TEST_KEY}");
    expect(new HttpClient().resolveHeaders(seen)["Authorization"]).toBe("Bearer sk-live-999");

    // No headers → exactly the pinned model_wire header set.
    let bare: Record<string, string> = {};
    new OpenAIEmbedder({ base_url: "http://x/v1", model: "m" }, (_u, _b, h) => {
      bare = h;
      return JSON.stringify({ data: [] });
    }).embed(["hi"]);
    expect(bare).toEqual({ "Content-Type": "application/json" });
  });
});
