// Build-time resolution of the CiteNexus LIBRARY version.
//
// Never hardcode this. This repo already shipped that bug once: `citenexus.__version__`
// sat at "0.2.0" through eight releases while PyPI served 0.9.0, because a test asserted
// the literal instead of reading the source of truth. A hardcoded string in an Astro
// config is the same bug with a nicer view.
//
// We read BOTH release-managed manifests and cross-check them:
//   - python/pyproject.toml  [project].version   (the reference implementation)
//   - js/package.json        version             (kept in step by the release process)
//
// NOTE: site/package.json is a DIFFERENT project (the docs site, 0.0.1). It is
// deliberately never consulted here.
//
// Any failure — file missing, field missing, or the two manifests disagreeing —
// throws, which fails `astro build`. A wrong or empty version badge is worse than none.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// This module is loaded by astro.config.mjs in plain Node (never bundled), so
// `import.meta.url` is the real on-disk path: site/src/components/ -> repo root.
// Components consume the resolved value through the `virtual:citenexus/version`
// module the config registers; they must not import this file directly, or the
// bundler will rewrite `import.meta.url` to the output chunk's location.
const REPO_ROOT = new URL('../../../', import.meta.url);
const PYPROJECT = new URL('python/pyproject.toml', REPO_ROOT);
const JS_PACKAGE = new URL('js/package.json', REPO_ROOT);

const SEMVER = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;

function read(url) {
	try {
		return readFileSync(url, 'utf8');
	} catch (cause) {
		throw new Error(
			`[citenexus:version] cannot read ${fileURLToPath(url)} — refusing to render a ` +
				`version badge from an unreadable source.`,
			{ cause }
		);
	}
}

/** `[project]` table only — do not pick up a version from [tool.*] or a dependency pin. */
function pyprojectVersion() {
	const text = read(PYPROJECT);
	const project = text.split(/^\[/m).find((section) => section.startsWith('project]'));
	if (!project) {
		throw new Error(`[citenexus:version] no [project] table in ${fileURLToPath(PYPROJECT)}`);
	}
	const match = project.match(/^\s*version\s*=\s*["']([^"']+)["']/m);
	if (!match) {
		throw new Error(
			`[citenexus:version] no [project].version in ${fileURLToPath(PYPROJECT)}`
		);
	}
	return match[1].trim();
}

function jsPackageVersion() {
	const path = fileURLToPath(JS_PACKAGE);
	let parsed;
	try {
		parsed = JSON.parse(read(JS_PACKAGE));
	} catch (cause) {
		throw new Error(`[citenexus:version] ${path} is not valid JSON`, { cause });
	}
	if (typeof parsed.version !== 'string' || parsed.version.trim() === '') {
		throw new Error(`[citenexus:version] no "version" string in ${path}`);
	}
	return parsed.version.trim();
}

function resolve() {
	const python = pyprojectVersion();
	const js = jsPackageVersion();

	if (python !== js) {
		throw new Error(
			`[citenexus:version] version drift — ${fileURLToPath(PYPROJECT)} says "${python}" but ` +
				`${fileURLToPath(JS_PACKAGE)} says "${js}". The release process keeps these in ` +
				`step; one of them was missed. Fix the manifests rather than the docs site.`
		);
	}
	if (!SEMVER.test(python)) {
		throw new Error(`[citenexus:version] "${python}" is not a semver version string`);
	}
	return python;
}

/** e.g. "0.10.1" — the version the docs describe. */
export const CITENEXUS_VERSION = resolve();

/** Release page for this exact version. Tags are published as `v<version>`. */
export const CITENEXUS_RELEASE_URL = `https://github.com/muthuishere/citenexus/releases/tag/v${CITENEXUS_VERSION}`;
