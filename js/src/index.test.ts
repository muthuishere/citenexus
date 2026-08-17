// The package's public entry point is a promise, and this is the test that keeps
// it.
//
// site/src/content/docs/custom-endpoints.mdx tells readers to write
// `import { OpenAIEmbedder, HttpClient } from "@muthuishere/citenexus"`. Until
// now `index.ts` re-exported `http.js` but NOT `models/`, so `HttpClient`
// resolved and `OpenAIEmbedder` did not — anyone following the page got an
// ImportError on a documented one-liner. A doc page cannot assert; this can.

import { describe, expect, it } from "vitest";

import * as pkg from "./index.js";

describe("the public entry point", () => {
  // Exactly the names the custom-endpoints page instructs a reader to import.
  const documented = ["OpenAIEmbedder", "HttpClient"] as const;

  for (const name of documented) {
    it(`exposes ${name}`, () => {
      expect(pkg).toHaveProperty(name);
      expect(typeof (pkg as Record<string, unknown>)[name]).toBe("function");
    });
  }

  it("exposes every shipped model client", () => {
    // Parity with Python, which exports its model clients top-level.
    for (const name of ["OpenAIEmbedder", "OpenAIChatGenerator", "AnthropicGenerator"]) {
      expect(pkg).toHaveProperty(name);
    }
  });

  it("constructs the documented client pair without touching the network", () => {
    const http = new pkg.HttpClient();
    const embed = new pkg.OpenAIEmbedder(
      {
        base_url: "https://api.jina.ai/v1",
        model: "jina-embeddings-v3",
        headers: { Authorization: "Bearer ${JINA_API_KEY}" },
      },
      (url, body, headers) => http.send(url, body, headers),
    );
    expect(embed).toBeInstanceOf(pkg.OpenAIEmbedder);
  });
});
