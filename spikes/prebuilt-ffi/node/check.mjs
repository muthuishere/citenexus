// TS/JS loader — koffi (single prebuilt-friendly FFI dep). Loads the prebuilt core.
import koffi from 'koffi';

const libPath = process.env.SPIKE_LIB;
const lib = koffi.load(libPath);

const version = lib.func('citenexus_spike_version', 'str', []);
const add = lib.func('citenexus_spike_add', 'int', ['int', 'int']);

const ver = version();
const total = add(2, 3);
console.log(`[node] version=${ver} add(2,3)=${total}`);

if (ver !== 'citenexus-spike-0.1.0' || total !== 5) {
  console.error('[node] MISMATCH');
  process.exit(1);
}
console.log('[node] OK');
