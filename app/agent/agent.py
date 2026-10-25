from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from app.agent.client import NebiusClient
from app.agent.memory import MemoryManager, detect_memory_candidate
from app.agent.permissions import PermissionManager
from app.agent.planner import create_plan
from app.agent.skills import select_skill
from app.agent.tools import ToolManager
from app.agent.verifier import verify_text
from app.database.database import Database


class PersonalAgent:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.memory = MemoryManager(database)
        self.permissions = PermissionManager(database)
        self.tools = ToolManager()
        self.client = NebiusClient()

    def _execute_approved_action(self, approval: dict[str, Any]) -> str:
        if approval["action"] == "write_file":
            payload = approval.get("payload") or ""
            if "\n" not in payload:
                raise RuntimeError("The pending file action has no stored file content.")
            filename, content = payload.split("\n", 1)
            result = self.tools.write_file(filename, content)
            if self.tools.read_file(filename) != content:
                raise RuntimeError(f"Verification failed for {filename}.")
        elif approval["action"] == "create_folder":
            result = self.tools.create_folder(approval["resource"])
            if not (self.tools.workspace / approval["resource"]).is_dir():
                raise RuntimeError(f"Verification failed for folder {approval['resource']}.")
        else:
            raise RuntimeError(f"Action {approval['action']} cannot be executed automatically.")
        return result

    async def run(self, message: str, emit: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        if not message.strip():
            raise ValueError("Please enter a request.")

        trace: list[dict[str, str]] = []

        def status(label: str, detail: str) -> None:
            item = {"label": label, "detail": detail}
            trace.append(item)
            self.database.add_activity(label, detail)
            if emit:
                emit(item)

        self.database.add_conversation("user", message)
        status("Memory retrieved", "Searching persistent memories relevant to this request.")
        memories = self.memory.retrieve_relevant_memories(message)
        approval_intent = any(
            phrase in message.lower()
            for phrase in ("approve", "approved", "approving", "go ahead", "create it now")
        )
        if approval_intent:
            pending = self.database.list_approvals()
            if pending:
                approval = pending[0]
                try:
                    result = self._execute_approved_action(approval)
                    self.database.resolve_approval(approval["id"], "approved")
                    status("Action approved", f"Approved {approval['action']}.")
                    status("Action completed", f"Created {result}.")
                    status("Verifying result", "Confirmed the requested workspace item exists.")
                    response = f"Created `{result}` in the workspace."
                except (OSError, ValueError, RuntimeError) as exc:
                    self.database.resolve_approval(approval["id"], "rejected")
                    raise RuntimeError(f"The approved action could not be completed: {exc}") from exc
                self.database.add_conversation("assistant", response)
                return {
                    "response": response,
                    "trace": trace,
                    "memories": memories,
                    "plan": ["Resolve the pending approval", "Execute the workspace action", "Verify the result"],
                    "skill": "controlled_action",
                    "execution": {"success": True, "resource": result},
                    "verification": {"success": True, "detail": "The workspace artifact was read back successfully."},
                }
        candidate = detect_memory_candidate(message)
        if candidate:
            saved = self.memory.save_memory(candidate.content, candidate.memory_type, candidate.importance)
            status("Memory saved", f"Saved memory #{saved['id']}.")
            response = f"Saved your memory: {saved['content']}"
            self.database.add_conversation("assistant", response)
            return {
                "response": response,
                "trace": trace,
                "memories": [saved],
                "plan": ["Identify useful personal information", "Save it to persistent storage", "Confirm the saved memory"],
                "skill": "memory",
                "memory": saved,
            }
        plan = create_plan(message)
        lower = message.lower()
        if memories and ("current goal" in lower or "what is my goal" in lower):
            goals = [memory for memory in memories if memory["memory_type"] == "goal"]
            if goals:
                response = f"Your current goal is {goals[0]['content'].removeprefix('Your goal is ')}"
                status("Memory used", f"Retrieved goal memory #{goals[0]['id']} from persistent storage.")
                status("Verifying result", "Personal context matched a saved goal.")
                self.database.add_conversation("assistant", response)
                return {"response": response, "trace": trace, "memories": memories,
                        "plan": ["Retrieve the saved goal", "Answer from persistent memory"], "skill": "memory"}
        if memories and MemoryManager.is_broad_recall_request(message):
            details = "\n".join(f"- {memory['content']}" for memory in memories)
            response = f"Here is what I remember about you:\n{details}"
            status("Memory used", f"Retrieved {len(memories)} saved memory record(s) from persistent storage.")
            status("Verifying result", "Response is grounded in saved memories.")
            self.database.add_conversation("assistant", response)
            return {"response": response, "trace": trace, "memories": memories,
                    "plan": ["Retrieve saved memories", "Present the saved context"], "skill": "memory"}
        status("Goal understood", plan.goal)
        skill = select_skill(message)
        status("Skill selected", skill.name)
        workspace_question = any(
            phrase in lower
            for phrase in (
                "how many files", "what files", "list the files", "files did you create",
                "what have you created", "what is inside the folder", "what's inside the folder",
                "does the folder exist", "show my files",
            )
        )
        if workspace_question:
            folder_match = re.search(
                r"(?i)(?:inside|within|in)\s+(?:(?:the|my)\s+)?(?:folder|directory)\s+[`'\"]?([A-Za-z0-9_.-]+)",
                message,
            )
            folder = folder_match.group(1) if folder_match else None
            files = self.tools.list_files(folder)
            status("Tool selected", "Listing the actual workspace files.")
            status("Action completed", f"Found {len(files)} file(s) on disk.")
            status("Verifying result", "The response is grounded in the workspace filesystem.")
            if files:
                details = "\n".join(f"- {item['path']} ({item['size']} bytes)" for item in files)
                response = f"I found {len(files)} file(s) in the workspace:\n{details}"
            else:
                response = "I found no files in the requested workspace folder."
            self.database.add_conversation("assistant", response)
            return {
                "response": response,
                "trace": trace,
                "memories": memories,
                "plan": ["Inspect the workspace", "Count actual files", "Report verified paths"],
                "skill": "workspace_inspection",
                "files": files,
            }

        filename_pattern = r"[A-Za-z0-9_.-]+\.(?:md|txt|json|csv|py|js|html|css)"
        file_match = re.search(rf"(?i)(?:file|document)\s+[`'\"]?({filename_pattern})[`'\"]?", message)
        if not file_match:
            file_match = re.search(rf"(?i)[`'\"]?({filename_pattern})[`'\"]?", message)
        folder_match = re.search(
            r"(?i)(?:inside|within|in)\s+(?:(?:the|my)\s+)?(?:folder|directory)\s+[`'\"]?([A-Za-z0-9_.-]+)[`'\"]?",
            message,
        )
        if folder_match and folder_match.group(1).lower() in {"now", "here", "it", "this", "my", "project"}:
            folder_match = None
        if not folder_match:
            folder_match = re.search(r"(?i)(?:create|make)\s+(?:a|the)\s+folder\s+[`'\"]?([A-Za-z0-9_.-]+)[`'\"]?", message)
        if folder_match and folder_match.group(1).lower() in {"now", "here", "it", "this", "my"}:
            folder_match = None
        if not file_match:
            recent_text = "\n".join(item["content"] for item in self.database.recent_conversations())
            file_match = re.search(
                rf"(?i)[`'\"]?({filename_pattern})[`'\"]?",
                recent_text,
            )
        if not folder_match and ("inside the folder" in lower or "inside folder" in lower):
            recent_text = "\n".join(item["content"] for item in self.database.recent_conversations())
            folder_match = re.search(
                r"(?i)(?:inside|within|in)\s+(?:(?:the|my)\s+)?(?:folder|directory)\s+[`'\"]?([A-Za-z0-9_.-]+)[`'\"]?",
                recent_text,
            )
            if folder_match and folder_match.group(1).lower() in {"now", "here", "it", "this", "my", "project"}:
                folder_match = None
        is_file_request = any(
            phrase in lower
            for phrase in ("create the file", "create a file", "write the file", "save it", "add it into the folder",
                           "inside the folder", "inside folder", "approve", "go ahead", "create it")
        )
        is_file_request = is_file_request or bool(file_match and any(word in lower for word in ("create", "write", "save")))
        is_folder_request = any(phrase in lower for phrase in ("create a folder", "create the folder", "make a folder", "make the folder"))
        if is_file_request and file_match:
            filename = file_match.group(1)
            target = f"{folder_match.group(1)}/{filename}" if folder_match else filename
            status("Tool selected", f"Preparing workspace file {target}.")
            status("Executing action", "The generated draft is ready for an approval-gated file write.")
            recent_context = "\n".join(
                f"{item['role']}: {item['content']}" for item in self.database.recent_conversations()
            )
            response = await self.client.respond(
                "Create only the requested artifact content. Use the recent conversation to recover the actual "
                "artifact requirements. Do not include a preamble, conversational reply, or claim that you wrote "
                "a file. The output will be written verbatim to the requested file.\n\n"
                f"Recent conversation:\n{recent_context}",
                f"Create the requested file named {target} based on the conversation above.",
            )
            request = self.permissions.assess("write_file", "Create the requested workspace file.", target)
            approval = self.permissions.request_approval(request, f"{target}\n{response}")
            status("Waiting for approval", "Approve the pending file write to create it in the workspace.")
            return {"response": f"I prepared `{target}`. Approve the pending action and I will create and verify it.",
                    "trace": trace, "memories": memories, "plan": plan.steps, "skill": skill.name, "approval": approval}
        if is_folder_request and folder_match:
            request = self.permissions.assess("create_folder", "Create the requested workspace folder.", folder_match.group(1))
            approval = self.permissions.request_approval(request)
            status("Waiting for approval", "Approve the pending folder creation.")
            return {"response": f"I can create `{folder_match.group(1)}` inside the workspace. Approve the pending action to continue.",
                    "trace": trace, "memories": memories, "plan": plan.steps, "skill": skill.name, "approval": approval}
        if "delete" in lower or "send" in lower or "modify important" in lower:
            request = self.permissions.assess(
                "delete_file" if "delete" in lower else "send_external" if "send" in lower else "write_file",
                "This action can change data or communicate externally.",
                message[:200],
            )
            approval = self.permissions.request_approval(request)
            status("Waiting for approval", f"{request.action} requires your approval.")
            return {"response": "Approval is required before I can perform this action.", "trace": trace,
                    "memories": memories, "plan": plan.steps, "skill": skill.name, "approval": approval}

        status("Planning task", f"{len(plan.steps)} steps prepared.")
        context = "\n".join(f"- {memory['content']}" for memory in memories) or "No relevant saved memories."
        system = (
            "You are a personal AI assistant. Use the supplied memories as context, but do not invent facts. "
            "Answer clearly and mention uncertainty. Do not reveal hidden chain-of-thought.\n\n"
            f"Relevant persistent memories:\n{context}"
        )
        status("Executing action", "Generating the response through Nebius Token Factory.")
        response = await self.client.respond(system, message)
        verification = verify_text(response)
        status("Verifying result", verification.message)
        self.database.add_conversation("assistant", response)

        return {"response": response, "trace": trace, "memories": memories, "plan": plan.steps, "skill": skill.name}
