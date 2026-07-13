# CiteNexus CLI — command reference

All commands accept the global flags:

| Flag | Meaning |
|---|---|
| `--config <path>` | use an explicit config file instead of discovery |
| `--json` | machine-readable output (drive the CLI with this) |
| `--partition <name>` | operate on a named partition (default: `default`) |

## Commands

| Command | Does | Needs a model? |
|---|---|---|
| `citenexus init [dir]` | scaffold `citenexus.yaml` (commit-safe) | no |
| `citenexus config get <key>` | read a global config key | no |
| `citenexus config set <key> <value>` | write a global config key | no |
| `citenexus ingest <path>` | extract → chunk → embed → store | embedding (optional; lexical without it) |
| `citenexus retrieve "<q>"` | fused candidates, cite-only | no |
| `citenexus ask "<q>"` | grounded answer or refusal | llm (required) |
| `citenexus install --skills` | (re)install this skill into `~/.claude` and `~/.agents` | no |

## Config (dual-level, secrets by reference)

Resolution precedence, highest wins: **environment → project `./citenexus.yaml`
→ global `~/.config/citenexus/config.yaml` → built-in defaults**. The nearest
project file is discovered by walking up from the working directory.

Auth is expressed ONLY as `${ENV_VAR}` header templates:

```yaml
models:
  llm:
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
    headers:
      Authorization: "Bearer ${OPENAI_API_KEY}"
```

The `${OPENAI_API_KEY}` value is read from the environment and materialized only
in the outgoing HTTP request — never written to the config, a log, or this skill.

## LLM modes

- **`api`** (default): the CLI calls models directly with `${ENV}` header auth.
- **`skill`** (sequenced follow-on): the CLI emits durable model requests and an
  external fulfiller (this skill) answers and resumes, so the CLI holds no
  credential. Not wired yet — do not assume it.

## The Result shape (`ask --json`)

```json
{
  "answer": "...",
  "answer_language": "en",
  "mode": "strict",
  "evidence": { "decision": "answered" | "refused", "supporting_sources": 1, ... },
  "sources": [ { "document": "...", "passage": "<verbatim>", "passage_language": "en" } ],
  "missing_evidence": [], "conflicts": []
}
```

When `evidence.decision` is `"refused"`, the corpus did not contain sufficiently
relevant evidence. Relay that plainly.
