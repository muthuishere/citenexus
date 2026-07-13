#!/usr/bin/env node
// CiteNexus CLI launcher: resolve the platform binary for this {version,
// platform} (cached, or lazily downloaded + SHA256-verified on first run — so the
// package works even when postinstall was skipped), then exec it transparently.
import { spawn } from "node:child_process";
import { ensureBinary } from "../lib/install.mjs";

async function main() {
  let bin;
  try {
    bin = await ensureBinary();
  } catch (err) {
    console.error(String(err && err.message ? err.message : err));
    console.error(
      "citenexus: could not obtain the platform binary. Set CITENEXUS_BINARY to an " +
        "explicit path, or check network/CITENEXUS_DOWNLOAD_BASE."
    );
    process.exit(1);
  }
  const child = spawn(bin, process.argv.slice(2), { stdio: "inherit" });
  child.on("error", (err) => {
    console.error(`citenexus: failed to exec ${bin}: ${err.message}`);
    process.exit(1);
  });
  child.on("exit", (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exit(code ?? 0);
  });
}

main();
