"""Partition-scoped conversation memory.

Memory is context, not evidence. The answer path may use recalled turns to shape
the retrieval query, but citations still come only from retrieved Evidence Units.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from trustrag.answer.verify import content_tokens
from trustrag.domain.partition import PartitionPath
from trustrag.storage.backend import StorageBackend
from trustrag.storage.paths import Layer, layer_prefix


class MemoryTurn(BaseModel):
    """One conversation turn stored after a verified answer/refusal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str
    answer: str
    ts: str


class MemoryStore:
    """Append-only JSON memory per conversation id."""

    def __init__(
        self,
        backend: StorageBackend,
        partition: PartitionPath,
        *,
        max_turns: int = 20,
    ) -> None:
        self._backend = backend
        self._partition = partition
        self._max_turns = max_turns

    def append(self, conversation_id: str, question: str, answer: str) -> None:
        turns = list(self.load(conversation_id))
        turns.append(
            MemoryTurn(
                question=question,
                answer=answer,
                ts=datetime.now(UTC).isoformat(),
            )
        )
        self._save(conversation_id, tuple(turns[-self._max_turns :]))

    def load(self, conversation_id: str) -> tuple[MemoryTurn, ...]:
        key = self._key(conversation_id)
        if not self._backend.exists(key):
            return ()
        return tuple(MemoryTurn.model_validate(item) for item in self._backend.get_json(key))

    def recall(self, conversation_id: str, query: str, *, limit: int = 3) -> tuple[MemoryTurn, ...]:
        turns = self.load(conversation_id)
        terms = content_tokens(query)
        if not terms:
            return tuple(reversed(turns[-limit:]))
        scored: list[tuple[int, int, MemoryTurn]] = []
        for idx, turn in enumerate(turns):
            text = f"{turn.question} {turn.answer}"
            hits = len(terms & content_tokens(text))
            if hits:
                scored.append((hits, idx, turn))
        if not scored:
            return tuple(reversed(turns[-limit:]))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        return tuple(turn for _hits, _idx, turn in scored[:limit])

    def _save(self, conversation_id: str, turns: tuple[MemoryTurn, ...]) -> None:
        self._backend.put_json(
            self._key(conversation_id),
            [turn.model_dump(mode="json") for turn in turns],
        )

    def _key(self, conversation_id: str) -> str:
        safe_id = conversation_id.replace("/", "_")
        return f"{layer_prefix(Layer.knowledge, self._partition)}/memory/{safe_id}.json"
