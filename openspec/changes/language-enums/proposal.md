## Why

Language and script codes are **bare strings at every public entry point**, and
a bare string has no discoverable domain. Today:

```python
rag.ask(q, answer_language="tamiil")          # typo → resolves to itself, silently
rag.ask(q, search_languages=("en", "tam"))     # typo → raises, but only at call time
signals.unsupported_scripts                    # tuple[str, ...] — of what, exactly?
```

There is no way to *discover* that 41 search languages exist, that 14 scripts are
claimed, or that `"auto"` is a sentinel rather than a language. The code list is
also written down **three times** — `lang/search.py`, `tokenize.py`'s
`SUPPORTED_SCRIPTS`, and `js/src/gen/tables.ts` — with nothing but review holding
them together.

The owner's ask: *"make all languages as enum so it's better instead of raw
string"*, immediately qualified with *"they can put string — enum is just helpful
stuff, so it support both."* That qualification is the whole design constraint.

## What Changes

- **`Language` and `Script`, both `StrEnum`** (`citenexus/lang/codes.py`).
  `Language.TAMIL == "ta"` is `True`, `json.dumps(Language.TAMIL)` is `"ta"`, and
  `f"{Language.TAMIL}"` is `ta`. Serialization is byte-identical, which is what
  lets this land without moving a single conformance fixture.
- **Every public entry point accepts `str | Language`** — `ask`, `retrieve`,
  `stream`, `_extra_queries`, `resolve_answer_language`,
  `resolve_requested_answer_language`, `resolve_search_languages`, and the
  `MultilingualConfig` fields. **Never `Language` alone.** Plain strings stay
  first-class forever: no `DeprecationWarning`, no "prefer the enum" prose, no
  behaviour difference.
- **The code list stops being duplicated.** `SEARCH_LANGUAGES` is keyed by
  `Language` and its `scripts` are `Script`; `SUPPORTED_SCRIPTS` /
  `CONTINUOUS_SCRIPTS` become `frozenset[Script]`. The enums are the single
  definition; the tables are expressed in terms of them.
- **An opt-in strict alias.** `LanguageCode` / `ScriptCode` are `Literal[...]`
  aliases exported for callers who *want* `"tamiil"` to be a type error. They are
  deliberately **not** used in library signatures — narrowing a signature to a
  `Literal` would reject a caller's computed `str`, which is exactly the break the
  owner ruled out.
- **Ported.** Go gets `type Language string` / `type Script string` plus the
  constant set in `golang/lang` — a string-typed named type, so the literal
  `"ta"` still assigns cleanly. JS gets a frozen `const` object plus a
  `Language | (string & {})` union type — **not** a TS `enum` (see design.md).
- **Pinned by a conformance vector.** New `conformance/cases/languages.json`
  carries the 41-language table, the script sets and the `"auto"` sentinel;
  Python, Go and JS each assert their constant set against it, exactly the way
  the script table is already pinned.

## Impact

- **Additive only.** 0.10.1 is published to PyPI / npm / crates / Go; every
  existing string call site keeps working unchanged and un-warned.
- **No conformance fixture moves.** One fixture is *added*.
- Affected: `python/src/citenexus/lang/`, `tokenize.py`, `client.py`,
  `config/schema.py`, `answer/result.py`, `scripts/gen_conformance.py`;
  `golang/lang/`, `golang/tokenize/`; `js/src/lang/`, `js/src/tokenize/`.
