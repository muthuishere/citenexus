"""Warn-only validation against ``citenexus.validate.yaml`` (spec §15).

A deployment may ship an optional ``citenexus.validate.yaml`` allow-list with
``allowed_signals`` and/or ``allowed_doc_types``. When supplied, the live client's
declared ``signals`` (and ``doc_types``) are compared against it; any divergence
emits a :func:`warnings.warn` and *proceeds*. This contract NEVER raises — it is
advisory by design (§15), not enforcement. When no validation file is supplied,
or the file is absent, no check runs and no warning is emitted.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from citenexus.config.schema import CiteNexusConfig


def _load_allowlist(validate_path: str | Path) -> dict[str, Any] | None:
    """Read the validate.yaml, or return ``None`` when the file is absent."""
    path = Path(validate_path)
    if not path.is_file():
        return None
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        return {}
    return dict(loaded)


def validate_client(
    config: CiteNexusConfig, validate_path: str | Path | None = None
) -> CiteNexusConfig:
    """Compare the client against the allow-list, warning (never raising) on drift.

    Returns the unchanged ``config`` so this is a drop-in pass-through. A ``None``
    path, or a missing file, is a silent no-op.
    """
    if validate_path is None:
        return config

    allowlist = _load_allowlist(validate_path)
    if allowlist is None:
        return config

    allowed_signals = allowlist.get("allowed_signals")
    if allowed_signals is not None:
        allowed = set(allowed_signals)
        offending = sorted(s.value for s in config.signals if s.value not in allowed)
        if offending:
            warnings.warn(
                f"declared signals {offending} are outside allowed_signals "
                f"{sorted(allowed)} in {Path(validate_path).name}",
                stacklevel=2,
            )

    allowed_doc_types = allowlist.get("allowed_doc_types")
    if allowed_doc_types is not None and config.doc_types is not None:
        allowed_dt = set(allowed_doc_types)
        offending_dt = sorted(d for d in config.doc_types if d not in allowed_dt)
        if offending_dt:
            warnings.warn(
                f"declared doc_types {offending_dt} are outside allowed_doc_types "
                f"{sorted(allowed_dt)} in {Path(validate_path).name}",
                stacklevel=2,
            )

    return config
