// JS CONSUME side (mochallama pattern): the matching platform package —
// selected at INSTALL time by npm via its `os`/`cpu` fields in this package's
// optionalDependencies — carries the native cdylib. Here we resolve that
// installed platform package and koffi-load its lib. No toolchain, no rebuild.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { existsSync } from "node:fs";

const require = createRequire(import.meta.url);
const koffi = require("koffi");

const SCOPE = "@muthuishere";
const BASE = "citenexus-core-dist-spike";

function platformKey() {
  const os = process.platform; // 'darwin' | 'linux' | 'win32'
  const cpu = process.arch; // 'arm64' | 'x64'
  return `${os}-${cpu}`;
}

function libFileName() {
  if (process.platform === "win32") return "citenexus_core.dll";
  if (process.platform === "darwin") return "libcitenexus_core.dylib";
  return "libcitenexus_core.so";
}

/** Resolve the bundled cdylib path from the installed platform package. */
export function coreLibPath() {
  const override = process.env.CITENEXUS_CORE_LIB;
  if (override) return override;
  const pkg = `${SCOPE}/${BASE}-${platformKey()}`;
  let pkgDir;
  try {
    // resolve the platform package's own package.json, then its lib dir
    pkgDir = dirname(require.resolve(`${pkg}/package.json`));
  } catch {
    throw new Error(
      `citenexus-core: platform package ${pkg} is not installed. It should be ` +
        `pulled automatically via optionalDependencies for ${platformKey()}; ` +
        `if your platform is unsupported, set CITENEXUS_CORE_LIB to a built cdylib.`,
    );
  }
  const lib = join(pkgDir, libFileName());
  if (!existsSync(lib)) throw new Error(`citenexus-core: cdylib missing at ${lib}`);
  return lib;
}

let cached;
export function coreVersion() {
  if (!cached) {
    const lib = koffi.load(coreLibPath());
    cached = lib.func("citenexus_core_version", "const char*", []);
  }
  return cached();
}
