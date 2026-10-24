from dataclasses import dataclass
import re
from typing import Any

from app.database.database import Database


@dataclass(frozen=True)
class MemoryCandidate:
    content: str
    memory_type: str
    importance: int


def detect_memory_candidate(message: str) -> MemoryCandidate | None:
    text = " ".join(message.strip().split())
    patterns = (
        (r"my goal is\s+(.+?)(?=\.\s+(?:create|save|before|after)\b|$)", "goal", 5),
        (r"i prefer\s+(.+?)(?=\.\s+(?:create|save|before|after)\b|$)", "preference", 4),
        (r"save this(?:\s*:\s*|\s+)(.+?)(?=\.\s+(?:create|save|before|after)\b|$)", "fact", 4),
        (r"(?:remember that|remember)\s+(.+?)(?=\.\s+(?:create|save|before|after)\b|$)", "fact", 4),
    )
    for pattern, memory_type, importance in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        detail = match.group(1).strip().rstrip(".!?")
        if detail.lower().startswith("my goal is "):
            detail = detail[11:].strip()
            memory_type = "goal"
            importance = 5
        if not detail:
            return None
        if memory_type == "fact" and detail.lower().startswith("my goal is "):
            content = f"Your goal is {detail[11:].strip()}."
            memory_type = "goal"
            importance = 5
        elif memory_type == "goal":
            content = f"Your goal is {detail}."
        elif memory_type == "preference":
            content = f"Your preference is {detail}."
        else:
            content = detail[0].upper() + detail[1:] + "."
        return MemoryCandidate(content, memory_type, importance)
    return None


class MemoryManager:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_memory(self, content: str, memory_type: str = "interaction", importance: int = 3) -> dict[str, Any]:
        allowed = {"preference", "fact", "goal", "task", "interaction", "project/context"}
        if memory_type not in allowed:
            raise ValueError(f"Unsupported memory type: {memory_type}")
        if not content.strip():
            raise ValueError("Memory content cannot be empty.")
        return self.database.add_memory(content, memory_type, max(1, min(5, importance)))

    def search_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        normalized_query = re.sub(r"[^\w\s-]", " ", query.lower())
        return self.database.search_memories(normalized_query, limit)

    def retrieve_relevant_memories(self, message: str) -> list[dict[str, Any]]:
        if self.is_broad_recall_request(message):
            return self.list_memories()
        return self.search_memory(message)

    @staticmethod
    def is_broad_recall_request(message: str) -> bool:
        normalized = " ".join(message.lower().split())
        return any(
            phrase in normalized
            for phrase in ("what do you remember", "what do you know about me", "show my memories")
        )

    def delete_memory(self, memory_id: int) -> None:
        self.database.delete_memory(memory_id)

    def list_memories(self) -> list[dict[str, Any]]:
        return self.database.list_memories()
