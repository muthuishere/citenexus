import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  assetName,
  binaryPath,
  ensureBinary,
  parseChecksums,
  platformKey,
  releaseTag,
  verifyChecksum,
} from "../lib/install.mjs";

function sha256(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

// A local release server: serves /v<version>/SHA256SUMS and the asset. `tamper`
// corrupts the asset body so the published checksum no longer matches.
async function startReleaseServer({ version, body, tamper = false }) {
  const key = platformKey();
  const asset = assetName(key);
  const tag = releaseTag(version, {});
  const realDigest = sha256(Buffer.from(body));
  const served = tamper ? Buffer.from(body + "-corrupted") : Buffer.from(body);
  let hits = 0;
  const server = createServer((req, res) => {
    hits++;
    if (req.url === `/${tag}/SHA256SUMS`) {
      res.writeHead(200);
      res.end(`${realDigest}  ${asset}\n`);
    } else if (req.url === `/${tag}/${asset}`) {
      res.writeHead(200);
      res.end(served);
    } else {
      res.writeHead(404);
      res.end("no");
    }
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address();
  return {
    base: `http://127.0.0.1:${port}`,
    asset,
    get hits() {
      return hits;
    },
    close: () => new Promise((r) => server.close(r)),
  };
}

test("parseChecksums parses shasum -a 256 output", () => {
  const map = parseChecksums(
    "abc123\n" + // ignored (not 64 hex)
      `${"a".repeat(64)}  citenexus-linux-x64\n` +
      `${"b".repeat(64)} *citenexus-win-x64.exe\n`
  );
  assert.equal(map["citenexus-linux-x64"], "a".repeat(64));
  assert.equal(map["citenexus-win-x64.exe"], "b".repeat(64));
});

// Task 6.1 — the downloader verifies SHA256 and REFUSES a mismatched binary.
test("verifyChecksum refuses a mismatched file", async () => {
  const dir = await mkdtemp(join(tmpdir(), "cn-verify-"));
  const f = join(dir, "bin");
  await writeFile(f, "hello");
  await assert.rejects(() => verifyChecksum(f, "d".repeat(64)), /checksum mismatch/);
  // The true digest passes.
  await verifyChecksum(f, sha256(Buffer.from("hello")));
});

test("ensureBinary deletes and refuses a tampered download", async () => {
  const version = "9.9.9";
  const srv = await startReleaseServer({ version, body: "#!/bin/sh\necho hi\n", tamper: true });
  const cacheRoot = await mkdtemp(join(tmpdir(), "cn-cache-"));
  const opts = { version, downloadBase: srv.base, cacheRoot, env: {} };
  await assert.rejects(() => ensureBinary(opts), /checksum mismatch/);
  // The corrupt file must NOT be left in the cache.
  await assert.rejects(() => stat(binaryPath(opts)), /ENOENT/);
  await srv.close();
});

// Task 6.2 — lazy download on first run, cache-hit with no network, override.
test("ensureBinary downloads-then-verifies, then serves cache with no network", async () => {
  const version = "1.2.3";
  const body = "#!/bin/sh\necho citenexus\n";
  const srv = await startReleaseServer({ version, body });
  const cacheRoot = await mkdtemp(join(tmpdir(), "cn-cache-"));
  const opts = { version, downloadBase: srv.base, cacheRoot, env: {} };

  const first = await ensureBinary(opts);
  assert.equal((await readFile(first)).toString(), body);
  const afterFirst = srv.hits;
  assert.ok(afterFirst >= 2, "first run should fetch SHA256SUMS + asset");

  // Second call: cache hit, ZERO additional server hits.
  const second = await ensureBinary(opts);
  assert.equal(second, first);
  assert.equal(srv.hits, afterFirst, "cache hit must not touch the network");
  await srv.close();
});

test("CITENEXUS_BINARY bypasses download entirely", async () => {
  const explicit = "/opt/custom/citenexus";
  const got = await ensureBinary({
    version: "0.0.0",
    downloadBase: "http://127.0.0.1:1/should-not-be-hit",
    cacheRoot: "/nonexistent",
    env: { CITENEXUS_BINARY: explicit },
  });
  assert.equal(got, explicit);
});

test("releaseTag defaults to the CLI's custom cli-v<version> tag", () => {
  assert.equal(releaseTag("0.9.0", {}), "cli-v0.9.0");
  assert.equal(releaseTag("0.9.0", { CITENEXUS_RELEASE_TAG: "v9.9.9" }), "v9.9.9");
});

test("platformKey rejects unsupported platforms", () => {
  assert.throws(() => platformKey("sunos", "sparc"), /unsupported platform/);
  assert.throws(() => platformKey("darwin", "x64"), /Intel macOS/); // Apple silicon only
  assert.equal(platformKey("darwin", "arm64"), "darwin-arm64");
  assert.equal(platformKey("linux", "x64"), "linux-x64");
  assert.equal(assetName("win-x64"), "citenexus-win-x64.exe");
});
