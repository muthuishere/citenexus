# Design — language & script enums

## The one constraint everything else follows from

> *"they can put string — enum is just helpful stuff, so it support both"*

The enums are a **convenience layer**, not a migration. That rules out three
otherwise-obvious designs immediately:

| Rejected | Why |
|---|---|
| Python `Enum` / `class Language(Enum)` | `Language.TAMIL != "ta"`. Every string call site breaks, and `json.dumps` emits `"Language.TAMIL"`. Conformance fixtures move. |
| Narrowing signatures to `Language` | Rejects `"ta"`. The published 0.10.1 surface breaks. |
| `DeprecationWarning` on the string path | The owner ruled it out by name. Strings are not the old way. |

## Python — `StrEnum`, and what that buys (and does not)

`Language` and `Script` subclass `enum.StrEnum` (3.11+, already the house style —
`Signal`, `TrustMode`, `LexicalSignal` are all `StrEnum`). The properties that
matter:

- `Language.TAMIL == "ta"` → `True`; `hash` matches, so it is interchangeable as
  a `dict` key and in `set` membership. `SEARCH_LANGUAGES["ta"]` and
  `SEARCH_LANGUAGES[Language.TAMIL]` are the same lookup.
- `json.dumps(Language.TAMIL)` → `"ta"`. `Result` JSON and every conformance
  fixture are byte-identical. This is the property the drift guard verifies.
- `str.lower()`, `.strip()`, `"".join(...)`, `sorted(...)` all work and return
  plain `str`, so existing normalisation code is untouched.

**The one sharp edge: `repr`.** `f"{Script.TELUGU!r}"` is
`<Script.TELUGU: 'telugu'>`, not `'telugu'`. Two existing error messages
interpolate a script with `!r`, so those sites explicitly coerce
(`f"{str(script)!r}"`) to keep the message byte-identical. This is checked by the
existing `UnsupportedSearchLanguageError` message tests, which are not modified.

### What the type checker actually catches

Because `Language` *is* a `str`, `def ask(..., answer_language: str | Language)`
collapses to `str` — mypy will **not** flag `"tamiil"`. That is the honest cost of
the owner's constraint, and it is the right trade: the runtime still refuses
`"tamiil"` by name, before any model call.

For callers who want the compile-time catch, we export opt-in `Literal` aliases:

```python
from citenexus.lang import Language, LanguageCode

def my_ask(code: LanguageCode) -> None: ...   # "tamiil" is now a type error
my_ask("ta")            # ok
my_ask(Language.TAMIL)  # ok — StrEnum members are assignable via their value? NO
```

`Language.TAMIL` is **not** assignable to `Literal["ta"]`, so `LanguageCode` is
defined as `Language | Literal["en", ...]` — accepting both, rejecting typos.
Library signatures stay `str | Language`; `LanguageCode` is for callers only.

### `Language.AUTO`

`"auto"` is a sentinel, not a language. It gets a member (`Language.AUTO`) so it
is discoverable next to the real codes, and `AUTO_ANSWER_LANGUAGE` is redefined as
`Language.AUTO` (still `== "auto"`). It is deliberately **absent from
`SEARCH_LANGUAGES`**, so `search_languages=("auto",)` still raises "unknown search
language" exactly as before.

## Go — a named string type, not an `iota` enum

```go
type Language string
const Tamil Language = "ta"
```

A defined string type keeps `var l Language = "ta"` legal (untyped constants
convert implicitly), so every existing literal call site compiles unchanged —
while `func F(l Language)` documents the domain and `go vet`/readers get the named
set. An `iota` int enum would have required a lookup table at every boundary and
broken JSON round-tripping against the shared fixtures.

Lives in `golang/lang` (which already owns the §11a chain and
`AutoAnswerLanguage`). `Script` lives there too rather than in `golang/tokenize`,
so the two constant sets that the conformance vector pins together are declared
together; `golang/tokenize` keeps its own `string`-based script functions
untouched (`golang/lang` must not import `golang/tokenize`, and does not).

## JS — `const` object + union, **not** a TS `enum`

A TS `enum` is the wrong tool for a published library, for three reasons:

1. **Nominal typing breaks the string path.** With `enum Language { Tamil = "ta" }`,
   the type `Language` does **not** accept the literal `"ta"`. Every existing
   `answerLanguage: "ta"` call becomes a type error — precisely the break the
   owner ruled out.
2. **It is not erasable.** `enum` emits runtime code, so it is illegal under
   `verbatimModuleSyntax` + `erasableSyntaxOnly` and under Node's built-in type
   stripping. A library that publishes `.d.ts` should not force that on consumers.
3. **It does not tree-shake** — the emitted IIFE is retained whole.

So:

```ts
export const Language = { ENGLISH: "en", TAMIL: "ta", ... } as const;
export type Language = (typeof Language)[keyof typeof Language];
export type LanguageLike = Language | (string & {});
```

`LanguageLike` is what public signatures take. The `(string & {})` arm is the
standard trick that keeps IDE autocomplete showing the 41 known codes **while
still accepting any string** — the JS mirror of `str | Language`.

## The conformance vector

`conformance/cases/languages.json` (new, generated by
`python/scripts/gen_conformance.py`):

```json
{
  "auto_sentinel": "auto",
  "scripts": ["arabic", ...],           // every Script member, sorted
  "supported_scripts": [...],           // == cases/tokenize_v2.json's, cross-checked
  "continuous_scripts": [...],
  "languages": [{"code": "en", "name": "English",
                 "scripts": ["latin"], "supported": true}, ...]
}
```

Python's drift guard regenerates it; Go and JS each assert their constant set
against it. That is the same three-way pin the script table already has, so the
41 codes cannot diverge across ports by review error.

## Deliberately out of scope

- Porting `resolve_search_languages` (the refusal logic) to Go/JS. The ports
  carry the **table**, which is what the vector pins; the resolution policy stays
  a Python-facade concern until a port needs it.
- Any change to `script_of`'s classification or to `SUPPORTED_SCRIPTS`' contents.
  ADR-0011's rule is untouched: no script joins the claim without a fixture.
