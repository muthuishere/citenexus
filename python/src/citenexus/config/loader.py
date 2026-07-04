"""Config loader: dict / YAML / environment with a defined precedence (§17).

``from_config`` is the front door. It accepts a Python ``dict``/mapping, a YAML
string, or a YAML file path as the base ``source``, then layers an optional
explicit ``overrides`` mapping and finally environment variables on top. The
precedence, lowest to highest, is::

    defaults  <  YAML/dict source  <  overrides  <  environment

Later sources win on a per-key, deep-merge basis. Environment variables use the
``CITENEXUS_`` prefix with ``__`` as the nesting separator, e.g.
``CITENEXUS_TRUST__DEFAULT_MODE=strict`` sets ``trust.default_mode``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from citenexus.config.schema import CiteNexusConfig

ENV_PREFIX = "CITENEXUS_"


def _source_to_dict(source: Mapping[str, Any] | str | Path | None) -> dict[str, Any]:
    """Coerce a dict / YAML string / YAML file path into a plain dict."""
    if source is None:
        return {}
    if isinstance(source, Mapping):
        return dict(source)

    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
    else:
        # A str is either a path to an existing file or literal YAML content.
        candidate = Path(source)
        try:
            is_file = candidate.is_file()
        except OSError:
            is_file = False
        text = candidate.read_text(encoding="utf-8") if is_file else source

    loaded: object = yaml.safe_load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise TypeError("Config YAML must define a mapping at the top level")
    return dict(loaded)


def _env_to_nested(env: Mapping[str, str], prefix: str) -> dict[str, Any]:
    """Turn ``CITENEXUS_A__B=v`` style vars into ``{'a': {'b': 'v'}}``."""
    result: dict[str, Any] = {}
    for key, value in env.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix) :].lower().split("__")
        cursor = result
        for part in path[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[path[-1]] = value
    return result


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` onto ``base``; overlay scalars win."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def from_config(
    source: Mapping[str, Any] | str | Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    env_prefix: str = ENV_PREFIX,
) -> CiteNexusConfig:
    """Build a :class:`CiteNexusConfig` from a source + overrides + environment.

    Precedence (lowest to highest): defaults < ``source`` < ``overrides`` < ``env``.
    ``env`` defaults to the process environment (``os.environ``); pass ``env={}``
    to opt out entirely.
    """
    data = _source_to_dict(source)
    if overrides:
        data = _deep_merge(data, overrides)
    environ: Mapping[str, str] = os.environ if env is None else env
    env_data = _env_to_nested(environ, env_prefix)
    if env_data:
        data = _deep_merge(data, env_data)
    return CiteNexusConfig.model_validate(data)
