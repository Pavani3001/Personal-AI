from dataclasses import dataclass


@dataclass(frozen=True)
class Verification:
    success: bool
    message: str


def verify_text(result: str) -> Verification:
    return Verification(bool(result.strip()), "Result verified." if result.strip() else "Result was empty.")
