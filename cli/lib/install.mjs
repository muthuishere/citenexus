// Shared install/launch logic for the CiteNexus CLI npm package: platform
// detection, cache paths, SHA256-verified download from GitHub Releases, and
// binary resolution. Both bin/citenexus.mjs (launcher) and scripts/postinstall.mjs
// import this. Every filesystem/network dependency is injectable so the behavior
// is testable offline against a local server. Zero third-party dependencies.

import { createHash } from "node:crypto";
import { createWriteStream } from "node:fs";
import { chmod, mkdir, rename, rm, stat, readFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

// version is read from package.json at load time (single source of truth).
export async function packageVersion(env = process.env) {
  if (env.CITENEXUS_VERSION) return env.CITENEXUS_VERSION;
  const pkgUrl = new URL("../package.json", import.meta.url);
  const pkg = JSON.parse(await readFile(pkgUrl, "utf8"));
  return pkg.version;
}

// Default GitHub Releases download base. Assets live under
// ${base}/<tag>/<asset> with a sibling SHA256SUMS file. The CLI ships as its OWN
// custom release (tag `cli-v<version>`), decoupled from the core's `v*` releases.
export const DEFAULT_DOWNLOAD_BASE =
  "https://github.com/muthuishere/citenexus/releases/download";

// releaseTag is the GitHub release the binary is pulled from. The CLI's custom
// release is tagged `cli-v<version>`; $CITENEXUS_RELEASE_TAG overrides it (mirrors
// / testing).
export function releaseTag(version, env = process.env) {
  return env.CITENEXUS_RELEASE_TAG || `cli-v${version}`;
}

// platformKey maps this runtime to an <os>-<arch> token. Throws on unsupported.
export function platformKey(platform = process.platform, arch = process.arch) {
  const os = { darwin: "darwin", linux: "linux", win32: "win" }[platform];
  const cpu = { arm64: "arm64", x64: "x64" }[arch];
  if (!os || !cpu) {
    throw new Error(`citenexus: unsupported platform ${platform}/${arch}`);
  }
  return `${os}-${cpu}`;
}

// assetName is the release asset for a platform key: citenexus-<os>-<arch>(.exe).
export function assetName(key = platformKey()) {
  return key.startsWith("win-") ? `citenexus-${key}.exe` : `citenexus-${key}`;
}

// binaryName is the on-disk executable name (adds .exe on Windows).
export function binaryName(key = platformKey()) {
  return key.startsWith("win-") ? "citenexus.exe" : "citenexus";
}

// cacheRoot is $CITENEXUS_CACHE or ~/.cache/citenexus.
export function cacheRoot(env = process.env, home = homedir()) {
  return env.CITENEXUS_CACHE || join(home, ".cache", "citenexus");
}

// binaryPath is <cacheRoot>/<version>/<platform>/citenexus(.exe).
export function binaryPath(opts = {}) {
  const env = opts.env || process.env;
  const key = opts.platform || platformKey();
  const version = opts.version;
  const root = opts.cacheRoot || cacheRoot(env, opts.home);
  return join(root, version, key, binaryName(key));
}

async function fileExists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

// sha256File returns the lowercase hex digest of a file.
export async function sha256File(path) {
  const hash = createHash("sha256");
  hash.update(await readFile(path));
  return hash.digest("hex");
}

// parseChecksums parses `shasum -a 256` output (`<hex>  <name>`) into a map.
export function parseChecksums(text) {
  const map = {};
  for (const line of text.split("\n")) {
    const m = line.trim().match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (m) map[m[2].trim()] = m[1].toLowerCase();
  }
  return map;
}

// httpGet fetches a URL, honoring HTTPS_PROXY when a proxy dispatcher is available
// (best-effort; falls back to a direct connection). Returns a fetch Response.
async function httpGet(url, env) {
  const proxy = env.HTTPS_PROXY || env.https_proxy;
  let dispatcher;
  if (proxy) {
    try {
      const { ProxyAgent } = await import("undici");
      dispatcher = new ProxyAgent(proxy);
    } catch {
      // undici ProxyAgent unavailable — proceed with a direct connection.
    }
  }
  const res = await fetch(url, dispatcher ? { dispatcher } : undefined);
  if (!res.ok) throw new Error(`citenexus: GET ${url} → HTTP ${res.status}`);
  return res;
}

// download streams url into dest atomically (via a temp file + rename).
export async function download(url, dest, env = process.env) {
  await mkdir(dirname(dest), { recursive: true });
  const res = await httpGet(url, env);
  const tmp = join(tmpdir(), `citenexus-dl-${process.pid}-${Date.now()}`);
  await pipeline(Readable.fromWeb(res.body), createWriteStream(tmp));
  await rename(tmp, dest);
  return dest;
}

// fetchText downloads a small text resource (e.g. SHA256SUMS).
export async function fetchText(url, env = process.env) {
  const res = await httpGet(url, env);
  return res.text();
}

// verifyChecksum throws unless the file's SHA256 equals expected (lowercase hex).
export async function verifyChecksum(path, expected) {
  const actual = await sha256File(path);
  if (!expected) {
    throw new Error(`citenexus: no published checksum to verify ${path}`);
  }
  if (actual.toLowerCase() !== expected.toLowerCase()) {
    throw new Error(
      `citenexus: checksum mismatch — refusing to run ${path} (expected ${expected}, got ${actual})`
    );
  }
}

// downloadBase resolves the release base URL (mirror override wins).
export function downloadBase(env = process.env) {
  return env.CITENEXUS_DOWNLOAD_BASE || DEFAULT_DOWNLOAD_BASE;
}

// ensureBinary returns a path to a verified, executable binary, downloading it if
// necessary. Resolution order:
//   1. $CITENEXUS_BINARY (explicit path) — used as-is, no download, no checksum.
//   2. a cached binary for this {version, platform} — re-used with NO network.
//   3. download <base>/v<version>/<asset>, verify against the release SHA256SUMS,
//      chmod +x, cache, and return it.
// A tampered download is deleted and refused.
export async function ensureBinary(opts = {}) {
  const env = opts.env || process.env;
  if (env.CITENEXUS_BINARY) return env.CITENEXUS_BINARY;

  const version = opts.version || (await packageVersion(env));
  const key = opts.platform || platformKey();
  const dest = binaryPath({ ...opts, env, version, platform: key });

  if (!opts.force && (await fileExists(dest))) {
    return dest; // cache hit — no network.
  }

  const base = opts.downloadBase || downloadBase(env);
  const tag = opts.tag || releaseTag(version, env);
  const asset = assetName(key);
  const sumsText = await fetchText(`${base}/${tag}/SHA256SUMS`, env);
  const sums = parseChecksums(sumsText);
  const expected = sums[asset];
  if (!expected) {
    throw new Error(`citenexus: ${asset} not listed in SHA256SUMS for ${tag}`);
  }

  await download(`${base}/${tag}/${asset}`, dest, env);
  try {
    await verifyChecksum(dest, expected);
  } catch (err) {
    await rm(dest, { force: true });
    throw err;
  }
  await chmod(dest, 0o755);
  return dest;
}
