"""pytest plugin: shadow-run is_supported_v2 alongside the shipped gate.

Patches every module-level import of `is_supported` with a wrapper that returns
the SHIPPED verdict (so the suite behaves exactly as before) while recording
what the ADR-0009 predicate would have decided. Writes $SHADOW_OUT as JSON.

Enabled with `-p shadow_gate`; the library source is untouched.
"""

from __future__ import annotations

import atexit
import json
import os

from citenexus.answer import agentic, flow
from citenexus.answer import verify as verify_mod
from citenexus.cli import cite_check
from citenexus.cli import verify as cli_verify
from predicate import is_supported_v2

_ORIG = verify_mod.is_supported
_LOG: list[dict] = []


def _shadow(answer: str, passage: str) -> bool:
    v0 = _ORIG(answer, passage)
    try:
        v2 = is_supported_v2(answer, passage)
    except Exception as exc:  # pragma: no cover - spike safety
        v2 = False
        _LOG.append({"error": repr(exc), "claim": answer[:200], "passage": passage[:200]})
        return v0
    _LOG.append({"claim": answer[:200], "passage": passage[:200], "v0": v0, "v2": v2})
    return v0


for _mod in (verify_mod, flow, agentic, cite_check, cli_verify):
    _mod.is_supported = _shadow  # type: ignore[attr-defined]


@atexit.register
def _dump() -> None:
    out = os.environ.get("SHADOW_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(_LOG, fh)
