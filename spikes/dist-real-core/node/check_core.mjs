// TS/JS loader — koffi (single prebuilt-friendly FFI dep). Loads the REAL core.
// Binds the actual `citenexus-core` cdylib and calls `citenexus_core_version()`.
import koffi from 'koffi';

const libPath = process.env.CORE_LIB;
const lib = koffi.load(libPath);

// 'str' marshals a NUL-terminated const char*; the returned pointer is a 'static
// crate string (not malloc'd) so there is nothing to free.
const version = lib.func('citenexus_core_version', 'str', []);

const ver = version();
console.log(`[node] citenexus_core_version()=${JSON.stringify(ver)}`);

const expected = (process.env.EXPECT_CORE_VERSION || '').trim();
if (!/^\d+\.\d+\.\d+/.test(ver)) {
  console.error(`[node] MISMATCH: not a semver: ${ver}`);
  process.exit(1);
}
if (expected && ver !== expected) {
  console.error(`[node] MISMATCH: got ${ver}, expected ${expected}`);
  process.exit(1);
}
console.log('[node] OK');
