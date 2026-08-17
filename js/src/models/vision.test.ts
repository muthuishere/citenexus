// OpenAIVision — describe an image over an injected VL endpoint (§9).
//
// Mirrors `python/tests/vision/test_vision_client.py`: injected transport,
// temperature always sent, the image base64-encoded into an OpenAI `image_url`
// data URI, a non-JSON reply degrading to a usable caption. Plus the two things
// only a port test can prove: that `describePayload` sends the emitted payload
// VERBATIM, and that no key VALUE ever lives on the client.

import { describe, expect, it } from "vitest";

import { HttpClient } from "../http.js";
import { base64Encode } from "../vision/requests.js";
import { OpenAIVision, parseVisionDescription } from "./vision.js";

const PNG = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x20, 0x66, 0x61, 0x6b, 0x65,
]);

const DESCRIPTION = {
  short_caption: "Revenue chart",
  detailed_description: "A line chart of revenue over four quarters.",
  objects: ["axis", "line"],
  relationships: ["revenue rises each quarter"],
  ocr_text: "Q1 Q2 Q3 Q4",
};

interface Call {
  url: string;
  body: string;
  headers: Record<string, string>;
}

function recordingTransport(content: string = JSON.stringify(DESCRIPTION)) {
  const calls: Call[] = [];
  const transport = (url: string, body: string, headers: Record<string, string>): string => {
    calls.push({ url, body, headers });
    return JSON.stringify({ choices: [{ message: { content } }] });
  };
  return { calls, transport };
}

describe("OpenAIVision", () => {
  it("returns the record fields the model produced", async () => {
    const { transport } = recordingTransport();
    const client = new OpenAIVision({ base_url: "http://vl.test/v1", model: "m" }, transport);
    const out = await client.describe(PNG, "describe it");
    expect(out["short_caption"]).toBe("Revenue chart");
    expect(out["ocr_text"]).toBe("Q1 Q2 Q3 Q4");
  });

  it("posts the image as a base64 data URI with temperature always sent", async () => {
    const { calls, transport } = recordingTransport();
    const client = new OpenAIVision({ base_url: "http://vl.test/v1/", model: "m" }, transport);
    await client.describe(PNG, "describe it");
    const call = calls[0]!;
    expect(call.url).toBe("http://vl.test/v1/chat/completions");
    expect(call.body).toContain("data:image/png;base64,");
    expect(call.body).toContain(base64Encode(PNG));
    const body = JSON.parse(call.body) as Record<string, unknown>;
    // Always sent — a grounded description must be deterministic (§9).
    expect(body["temperature"]).toBe(0.0);
    expect("max_tokens" in body).toBe(false);
  });

  it("sends the emitted payload VERBATIM, without re-encoding", async () => {
    // The ADR-0005 seam: the core already assembled the data URI, so the host
    // must NOT re-encode it — otherwise what goes on the wire is not what the
    // conformance fixture pinned.
    const { calls, transport } = recordingTransport();
    const client = new OpenAIVision({ base_url: "http://vl.test/v1", model: "m" }, transport);
    await client.describePayload("data:image/jpeg;base64,QUJD", "the pinned prompt");
    expect(calls[0]!.body).toContain("data:image/jpeg;base64,QUJD");
    expect(calls[0]!.body).toContain("the pinned prompt");
  });

  it("holds an ${ENV} template for auth, never a key value", async () => {
    // The hard rule: a key VALUE never enters the client. It holds a ${ENV}
    // template and the transport expands it at the request boundary.
    process.env["CITENEXUS_TEST_VL_KEY"] = "super-secret-value";
    const { calls, transport } = recordingTransport();
    const client = new OpenAIVision(
      {
        base_url: "http://vl.test/v1",
        model: "m",
        headers: { Authorization: "Bearer ${CITENEXUS_TEST_VL_KEY}" },
      },
      transport,
    );
    await client.describe(PNG, "p");
    // What the client hands the transport is the TEMPLATE, unexpanded.
    expect(calls[0]!.headers["Authorization"]).toBe("Bearer ${CITENEXUS_TEST_VL_KEY}");
    // Only the transport resolves it, for one request.
    expect(new HttpClient().resolveHeaders(calls[0]!.headers)["Authorization"]).toBe(
      "Bearer super-secret-value",
    );
    delete process.env["CITENEXUS_TEST_VL_KEY"];
  });

  it("propagates a transport failure as a rejection", async () => {
    // A failed call must be an error the fulfiller can drop the request on —
    // never a silently empty description that assembles into a fabricated unit.
    const client = new OpenAIVision({ base_url: "http://vl.test/v1", model: "m" }, () => {
      throw new Error("boom");
    });
    await expect(client.describePayload("data:image/png;base64,QQ==", "p")).rejects.toThrow("boom");
  });
});

describe("parseVisionDescription", () => {
  it.each([
    ["plain json", '{"short_caption": "A chart"}', { short_caption: "A chart" }],
    // A model that wraps its JSON in a markdown fence still parses.
    ["fenced json", '```json\n{"short_caption": "A chart"}\n```', { short_caption: "A chart" }],
    // A model that ignores the JSON instruction still yields a usable caption —
    // degrade, not fail, and nothing invented beyond the model's own words.
    [
      "prose degrades to a caption",
      "Just a plain sentence.",
      { short_caption: "Just a plain sentence." },
    ],
    // A JSON array is not a record; the reference falls back too.
    ["non-object json degrades to a caption", '["a", "b"]', { short_caption: '["a", "b"]' }],
  ])("%s", (_name, content, want) => {
    expect(parseVisionDescription(content)).toEqual(want);
  });
});
