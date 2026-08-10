from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .conversation_store import ConversationStore, MessageRecord
from .memory_manager import MemoryManager
from .memory_store import MemoryRecord


@dataclass(frozen=True)
class ContextBundle:
    conversation_summary: str | None
    recent_messages: list[MessageRecord]
    memories: list[MemoryRecord]

    def render(self, max_chars: int = 12000) -> str:
        blocks: list[str] = []
        if self.conversation_summary:
            blocks.append("CONVERSATION SUMMARY\n" + self.conversation_summary.strip())
        if self.recent_messages:
            blocks.append("RECENT CONVERSATION\n" + "\n".join(
                f"{m.role.upper()}: {m.content}" for m in self.recent_messages
            ))
        if self.memories:
            lines = []
            for m in self.memories:
                refs = []
                for p in m.provenance:
                    if isinstance(p, dict):
                        ref = p.get("source_id") or p.get("artifact_id") or p.get("ref")
                        if ref:
                            refs.append(str(ref))
                lines.append(
                    f"- [{m.memory_id}] {m.namespace} | {m.subject} | {m.predicate} = {m.value_text} "
                    f"(confidence={m.confidence:.2f}; provenance={','.join(refs) or 'none'})"
                )
            blocks.append("DURABLE MEMORY\n" + "\n".join(lines))
        text = "\n\n".join(blocks)
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 30)] + "\n...[context truncated]"


class ContextBuilder:
    """Build bounded model context from conversation + memory. RAG stays separate."""

    def __init__(self, conversations: ConversationStore, memory: MemoryManager,
                 *, recent_message_limit: int = 10, memory_limit: int = 8):
        self.conversations = conversations
        self.memory = memory
        self.recent_message_limit = recent_message_limit
        self.memory_limit = memory_limit

    def build(self, *, query: str, conversation_id: str | None,
              namespaces: Iterable[str] | None = None, subject: str | None = None,
              exclude_request_id: str | None = None) -> ContextBundle:
        recent = []
        summary = None
        if conversation_id:
            # Pull one extra so excluding the current request does not shrink history.
            fetch_limit = self.recent_message_limit + (1 if exclude_request_id else 0)
            recent = self.conversations.recent_messages(conversation_id, limit=fetch_limit)
            if exclude_request_id:
                recent = [m for m in recent if m.request_id != exclude_request_id]
            recent = recent[-self.recent_message_limit:]
            summary = self.conversations.get_summary(conversation_id)
        memories = self.memory.search(query, namespaces=namespaces, subject=subject, limit=self.memory_limit)
        return ContextBundle(summary, recent, memories)
