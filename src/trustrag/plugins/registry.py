"""``PluginRegistry`` — typed registration with single-slot vs fusion semantics.

Registration is *typed, not duck-typed*: only an instance of one of the declared
protocol ABCs is accepted; anything else is rejected (``TypeError``). Single-slot
stages are last-wins; retrievers accumulate into a fusion *set* because the core
fusion step needs all of them. ``use(plugin)`` is the one public verb (§15): it
inspects the plugin's protocol type and routes it without the caller naming the
slot. Built-ins register through this same mechanism — there is no privileged
path.
"""

from __future__ import annotations

from trustrag.plugins.base import (
    ChunkerPlugin,
    EmbeddingPlugin,
    EvaluatorPlugin,
    ExtractorPlugin,
    GraphExtractorPlugin,
    JudgePlugin,
    LanguageDetectorPlugin,
    MemoryPlugin,
    Plugin,
    RerankerPlugin,
    RetrieverPlugin,
    VisionPlugin,
)

# The single-slot stages, keyed by their declared protocol (last-wins).
_SINGLE_SLOT_PROTOCOLS: tuple[type[Plugin], ...] = (
    ExtractorPlugin,
    ChunkerPlugin,
    EmbeddingPlugin,
    VisionPlugin,
    GraphExtractorPlugin,
    RerankerPlugin,
    JudgePlugin,
    EvaluatorPlugin,
    LanguageDetectorPlugin,
    MemoryPlugin,
)

# Every protocol, used to detect ambiguity (an object matching more than one).
_ALL_PROTOCOLS: tuple[type[Plugin], ...] = (*_SINGLE_SLOT_PROTOCOLS, RetrieverPlugin)


class PluginRegistry:
    """Holds the resolved plugin per single-slot stage plus the retriever set."""

    def __init__(self) -> None:
        self._slots: dict[type[Plugin], Plugin] = {}
        self._retrievers: list[RetrieverPlugin] = []

    # -- public API ---------------------------------------------------------

    def use(self, plugin: Plugin) -> None:
        """Register ``plugin`` by routing it to the correct slot by its type."""
        protocol = self._classify(plugin)
        if protocol is RetrieverPlugin:
            self.register_retriever(plugin)  # type: ignore[arg-type]
        else:
            self._validate_version(plugin)
            self._slots[protocol] = plugin

    def register(self, plugin: Plugin) -> None:
        """Register a single-slot plugin (last-wins). Retrievers are rejected."""
        protocol = self._classify(plugin)
        if protocol is RetrieverPlugin:
            raise TypeError(
                "RetrieverPlugin forms a fusion set; use register_retriever() or use()"
            )
        self._validate_version(plugin)
        self._slots[protocol] = plugin

    def register_retriever(self, plugin: RetrieverPlugin) -> None:
        """Add a retriever to the fusion set; multiple retrievers coexist."""
        if not isinstance(plugin, RetrieverPlugin):
            raise TypeError(
                f"expected a RetrieverPlugin, got {type(plugin).__name__!r}"
            )
        self._validate_version(plugin)
        self._retrievers.append(plugin)

    def resolve(self, protocol: type[Plugin]) -> Plugin:
        """Return the plugin registered for a single-slot ``protocol``."""
        return self._slots[protocol]

    @property
    def retrievers(self) -> tuple[RetrieverPlugin, ...]:
        """The retriever fusion set, in registration order."""
        return tuple(self._retrievers)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _classify(plugin: Plugin) -> type[Plugin]:
        """Return the single protocol ``plugin`` implements, or reject it."""
        matches = [p for p in _ALL_PROTOCOLS if isinstance(plugin, p)]
        if not matches:
            raise TypeError(
                f"{type(plugin).__name__!r} is not an instance of any plugin protocol"
            )
        if len(matches) > 1:
            names = ", ".join(p.__name__ for p in matches)
            raise TypeError(
                f"{type(plugin).__name__!r} matches multiple protocols ({names}); "
                "a plugin must implement exactly one"
            )
        return matches[0]

    @staticmethod
    def _validate_version(plugin: Plugin) -> None:
        version = getattr(plugin, "plugin_version", None)
        if not isinstance(version, str) or not version.strip():
            raise ValueError(
                f"{type(plugin).__name__!r} must declare a non-empty plugin_version "
                "(required for §4c provenance stamps)"
            )
