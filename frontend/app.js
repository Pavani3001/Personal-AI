const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, { headers: {"Content-Type": "application/json"}, ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "Request failed.");
  return body;
}

function addMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.innerHTML = `<strong>${role === "user" ? "You" : "Personal AI"}</strong><p></p>`;
  node.querySelector("p").textContent = text;
  $("#messages").append(node);
  node.scrollIntoView({behavior: "smooth"});
}

function renderTrace(items = []) {
  $("#trace").innerHTML = items.length ? items.map(item =>
    `<div class="trace-item"><strong>✓ ${item.label}</strong><span>${item.detail}</span></div>`).join("") :
    '<p class="muted">Your next run will appear here.</p>';
}

async function refreshPanels() {
  const [memories, approvals, schedules, activity] = await Promise.all([
    api("/api/memories"), api("/api/approvals"), api("/api/schedules"), api("/api/activity")
  ]);
  $("#memory-count").textContent = memories.length;
  $("#memories").innerHTML = memories.length ? memories.map(memory =>
    `<div class="memory"><strong>${escapeHtml(memory.content)}</strong><small>${memory.memory_type} · importance ${memory.importance}</small></div>`).join("") :
    '<p class="muted">No saved memories yet.</p>';
  $("#approval-count").textContent = approvals.length;
  $("#approvals").innerHTML = approvals.length ? approvals.map(item =>
    `<div class="approval"><strong>${escapeHtml(item.action)}</strong><small>${escapeHtml(item.resource)}</small>
      <button data-approval="${item.id}" data-status="approved">Approve</button>
      <button data-approval="${item.id}" data-status="rejected">Reject</button></div>`).join("") :
    '<p class="muted">No actions waiting.</p>';
  $("#schedules").innerHTML = schedules.length ? schedules.map(item =>
    `<div class="schedule"><strong>${escapeHtml(item.title)}</strong><small>${new Date(item.run_at).toLocaleString()} · ${item.status}${item.result ? ` · ${escapeHtml(item.result)}` : ""}</small></div>`).join("") : "";
  $("#activity").innerHTML = activity.length ? activity.slice(-8).reverse().map(item =>
    `<div class="schedule"><strong>✓ ${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail)} · ${new Date(item.created_at).toLocaleTimeString()}</small></div>`).join("") :
    '<p class="muted">Completed actions will appear here.</p>';
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[character]));
}

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("#message");
  const message = input.value.trim();
  if (!message) return;
  addMessage("user", message);
  input.value = "";
  renderTrace([{label: "Planning task", detail: "Working through the agent loop..."}]);
  try {
    const result = await api("/api/chat", {method: "POST", body: JSON.stringify({message})});
    addMessage("assistant", result.response);
    renderTrace(result.trace);
    await refreshPanels();
  } catch (error) { addMessage("assistant", `I could not complete that: ${error.message}`); }
});

$("#approvals").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-approval]");
  if (!button) return;
  try {
    const result = await api(`/api/approvals/${button.dataset.approval}`, {
      method: "POST", body: JSON.stringify({status: button.dataset.status})
    });
    if (result.execution?.success) addMessage("assistant", `Action completed: ${result.execution.resource}`);
    await refreshPanels();
  } catch (error) {
    addMessage("assistant", `The approved action failed: ${error.message}`);
  }
});

$("#schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/schedules", {method: "POST", body: JSON.stringify({
      title: $("#schedule-title").value, run_at: new Date($("#schedule-time").value).toISOString()
    })});
    event.target.reset();
    await refreshPanels();
  } catch (error) { alert(error.message); }
});

api("/api/health").then(data => {
  $("#health").textContent = data.nebius_configured ? "Connected" : "API key missing";
  $("#health").style.color = data.nebius_configured ? "#6df0b2" : "#ffb5a7";
}).catch(() => { $("#health").textContent = "Backend unavailable"; });
refreshPanels().catch(() => {});
setInterval(() => refreshPanels().catch(() => {}), 10000);
