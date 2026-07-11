# OpenSpec + Context Cheatsheet

How we run OpenSpec so context stays cheap. Read this before starting a change.

## The one idea

An OpenSpec **change folder is a durable context handoff.** Your reasoning lives
in committed files (`proposal` / `design` / `specs` / `tasks` + any ADR + memory),
not in the chat. That is what lets you `/clear` between phases without losing
anything — and clearing is what keeps each phase's context small and focused.

> **If it isn't written to disk (and committed) before you `/clear`, it's gone.**

`/clear` is free; `/compact` is paid. Clear at every phase boundary once the
phase's output is committed.

## The loop — one change at a time

```
Phase 0 Decide ─▶ Phase 1 Propose ─▶ commit ─▶ /clear
              ─▶ Phase 2 Apply   ─▶ commit ─▶ /clear
              ─▶ Phase 3 Archive ─▶ commit ─▶ /clear
```

Never hold two changes in one context.

### Phase 0 — Decide  (the only discussion-heavy phase)

- Resolve the design in conversation. This is where rich chat context earns its keep.
- **Architectural fork?** → write `docs/adr/NNNN-name.md` (why X over Y, alternatives).
- **Durable decision / gotcha?** → save it to memory.
- **CiteNexus gate check** (`CLAUDE.md` → "Where a new feature goes"): does it pass
  **both** gates — (1) ingests an artifact *or* improves grounded retrieval/eval,
  **and** (2) holds "no ungrounded claim"? If not → it's a **separate repo**. Stop here.

### Phase 1 — Propose

```bash
/opsx:propose <name-or-description>        # guided: writes all 4 artifacts
# — or manual —
openspec new change <name>
openspec status  --change <name> --json    # build order + applyRequires
openspec instructions <artifact> --change <name> --json   # template per artifact
openspec validate <name>                   # MUST print "is valid"
```

- Pour the Phase-0 decision **into the artifacts**. The chat is throwaway; the
  artifacts are the record. Build order: `proposal → design → specs → tasks`
  (`tasks` is the apply-required one).
- Commit docs-only: `docs(openspec): propose <name>`.
- **`/clear`.**

### Phase 2 — Apply  (fresh context)

```bash
/opsx:apply <name>                         # implement from tasks.md, TDD
```

- Fresh session loads only the change + the code it touches. Use **Explore /
  general-purpose subagents** for searches so file dumps stay out of the main window.
- Red → green → refactor down `tasks.md`; tick each `- [ ]` as you go.
- Commit implementation: `feat: … (<name>)` (or `fix:`/`docs:` as fits).
- **`/clear`.**

### Phase 3 — Archive

```bash
/opsx:archive <name>                       # folds the delta into openspec/specs/
```

- Commit: `docs(openspec): archive <name>`.
- **`/clear`** before the next change.

## Why clear between phases

Phase 0 wants the design discussion; Phase 2 wants the code; Phase 3 wants the spec
tree. Carrying one phase's context into the next just burns tokens for no benefit —
the committed artifacts already carry everything forward.

## Context hygiene (always on)

- **One change in flight** per context.
- Before `/clear`: is everything needed committed? (change folder, ADR, memory)
- **Name the change explicitly** in `/opsx:apply <name>` — don't make a fresh
  session rediscover it.
- Big searches / multi-file reads → a subagent, so dumps never enter main context.
- Don't re-read files already seen; summarize long tool output instead of repeating it.

## Command quick-ref

| Want | Command |
|---|---|
| new change | `openspec new change <name>` |
| what's left / build order | `openspec status --change <name> --json` |
| artifact template | `openspec instructions <proposal\|design\|specs\|tasks> --change <name> --json` |
| check valid | `openspec validate <name>` |
| list changes | `openspec list` |
| propose (guided) | `/opsx:propose <name-or-desc>` |
| implement | `/opsx:apply <name>` |
| fold into living spec | `/opsx:archive <name>` |

## Artifact roles

- **proposal.md** — *Why* + *What Changes* + *Capabilities* (new/modified) + *Impact*. Concise, the "why".
- **design.md** — *Context / Goals-NonGoals / Decisions (alternatives considered) / Risks / Migration*. Only for cross-cutting or ambiguous changes.
- **specs/&lt;cap&gt;/spec.md** — delta: `## ADDED|MODIFIED|REMOVED Requirements`,
  each `### Requirement:` uses **SHALL/MUST**, each `#### Scenario:` is **WHEN/THEN**.
  `MODIFIED` must include the **full** updated requirement text. New capability name =
  kebab-case; modified = existing folder name under `openspec/specs/`.
- **tasks.md** — `## N. Group` + `- [ ] N.M …` checkboxes, in **TDD / dependency order**.
  This is what `/opsx:apply` parses to track progress, so keep the checkbox format exact.

## Worked example (this repo)

`core-parse-two-phase-vision` — decided in chat + `docs/adr/0005-*`, proposed with all
four artifacts, `openspec validate` clean, committed docs-only. Next session: `/clear`
then `/opsx:apply core-parse-two-phase-vision` implements it TDD from `tasks.md`.
