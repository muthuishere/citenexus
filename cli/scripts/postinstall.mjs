// Best-effort prefetch of the platform binary at npm install time. A failure here
// is NEVER fatal: the launcher (bin/citenexus.mjs) lazily downloads + verifies on
// first run, so `--ignore-scripts`, offline, and CI installs all still work.
import { ensureBinary } from "../lib/install.mjs";

try {
  const bin = await ensureBinary();
  console.log(`citenexus: binary ready at ${bin}`);
} catch (err) {
  console.warn(
    `citenexus: could not prefetch the binary (${
      err && err.message ? err.message : err
    }); it will be downloaded on first run.`
  );
}
process.exit(0);
