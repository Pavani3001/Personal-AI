from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    allowed_tools: tuple[str, ...]


SKILLS = (
    Skill("research", "Find and organize information from the user's workspace.", ("read_file", "search")),
    Skill("summarize", "Turn supplied context into a concise explanation.", ("read_file",)),
    Skill("organize", "Create a structured task or project artifact.", ("write_file", "task")),
    Skill("task_planning", "Break a goal into verifiable steps.", ("task", "write_file")),
)


def select_skill(message: str) -> Skill:
    text = message.lower()
    if any(word in text for word in ("research", "find", "look up", "search")):
        return SKILLS[0]
    if any(word in text for word in ("summarize", "summary", "explain")):
        return SKILLS[1]
    if any(word in text for word in ("organize", "write", "create", "file")):
        return SKILLS[2]
    return SKILLS[3]
