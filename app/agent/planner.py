from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    goal: str
    steps: list[str]


def create_plan(message: str) -> Plan:
    text = message.strip()
    steps = ["Understand the goal", "Choose a suitable skill", "Execute a safe action", "Verify the result"]
    if any(word in text.lower() for word in ("create", "write", "file")):
        steps.insert(2, "Prepare the requested file change")
    return Plan(goal=text, steps=steps)
