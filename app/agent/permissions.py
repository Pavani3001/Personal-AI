from dataclasses import dataclass

from app.database.database import Database


@dataclass(frozen=True)
class ActionRequest:
    action: str
    reason: str
    resource: str
    risk: str


class PermissionManager:
    def __init__(self, database: Database) -> None:
        self.database = database

    def assess(self, action: str, reason: str, resource: str) -> ActionRequest:
        risk = "high" if action in {"delete_file", "send_external"} else "medium" if action == "write_file" else "low"
        return ActionRequest(action, reason, resource, risk)

    def requires_approval(self, request: ActionRequest) -> bool:
        return request.risk in {"medium", "high"}

    def request_approval(self, request: ActionRequest, payload: str | None = None) -> dict:
        return self.database.add_approval(request.action, request.reason, request.resource, payload)
