const queryEl    = document.getElementById("query");
const threadEl   = document.getElementById("threadId");
const genBtn     = document.getElementById("generateBtn");
const warnEl     = document.getElementById("warn");
const pipelineEl = document.getElementById("pipeline");
const agentsEl   = document.getElementById("agents");
const metricsEl  = document.getElementById("metrics");
const finalEl    = document.getElementById("final");
const finalCard  = document.getElementById("finalCard");
const dlBtn      = document.getElementById("downloadBtn");

const AGENTS = {
  supervisor:      { icon: "🧭", label: "Supervisor" },
  flight_agent:    { icon: "✈️", label: "Flight Agent" },
  hotel_agent:     { icon: "🏨", label: "Hotel Agent" },
  transport_agent: { icon: "🚇", label: "Transport Agent" },
  weather_agent:   { icon: "🌤️", label: "Weather Agent" },
  budget_agent:    { icon: "💰", label: "Budget Agent" },
  itinerary_agent: { icon: "🗓️", label: "Itinerary Agent" },
  human_approval:  { icon: "🙋", label: "Human Approval" },
  final_response:  { icon: "✅", label: "Final Response" },
};

let collected = {};
let userQuery = "";

/* ── Reveal on scroll ── */
const observer = new IntersectionObserver(
  (entries) => entries.forEach((e) => e.isIntersecting && e.target.classList.add("visible")),
  { threshold: 0.12 }
);
document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));

/* ── Quick chips ── */
document.querySelectorAll("#quickChips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    queryEl.value = chip.textContent;
    queryEl.focus();
  });
});

/* ── Destination chips: fill the search ── */
document.querySelectorAll(".dest-chip").forEach((el) => {
  el.addEventListener("click", () => {
    queryEl.value = el.dataset.q || "";
    queryEl.focus();
  });
});

/* ── Generate ── */
genBtn.addEventListener("click", generatePlan);
queryEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) generatePlan();
});

async function generatePlan() {
  const query = queryEl.value.trim();
  if (!query) {
    warnEl.classList.remove("hidden");
    return;
  }
  warnEl.classList.add("hidden");

  userQuery = query;
  collected = { itinerary: "", final_response: "", llm_calls: 0 };

  metricsEl.classList.add("hidden");
  finalEl.classList.add("hidden");
  finalCard.innerHTML = "";
  agentsEl.innerHTML = "";
  pipelineEl.classList.remove("hidden");
  pipelineEl.scrollIntoView({ behavior: "smooth", block: "start" });

  genBtn.disabled = true;
  genBtn.querySelector(".btn-label").textContent = "Running agents…";

  try {
    const res = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, thread_id: threadEl.value.trim() || "web_user" }),
    });
    if (!res.ok || !res.body) throw new Error("Server returned " + res.status);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const rawEvent = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of rawEvent.split("\n")) {
          if (!line.startsWith("data:")) continue;
          handleEvent(JSON.parse(line.slice(5).trim()));
        }
      }
    }
  } catch (err) {
    showError(err.message);
  } finally {
    genBtn.disabled = false;
    genBtn.querySelector(".btn-label").textContent = "Generate My Travel Plan";
  }
}

/* ── Pipeline UI (cards are created on demand: the supervisor picks the agents) ── */
function ensureCard(node) {
  let card = document.getElementById("card-" + node);
  if (card) return card;
  const meta = AGENTS[node] || { icon: "🔧", label: node };
  card = document.createElement("div");
  card.className = "agent-card running";
  card.id = "card-" + node;
  card.innerHTML = `
    <div class="agent-header">${meta.icon} ${meta.label}
      <span class="status running">Running</span>
    </div>
    <div class="agent-body skeleton">
      <div class="sk-line" style="width:85%"></div>
      <div class="sk-line" style="width:65%"></div>
      <div class="sk-line" style="width:75%"></div>
    </div>`;
  agentsEl.appendChild(card);
  return card;
}

function handleEvent(payload) {
  if (payload.type === "agent") {
    if (payload.node === "final_response") return; // card intentionally hidden
    ensureCard(payload.node);
    completeAgent(payload.node, payload.text);
  } else if (payload.type === "question") {
    showQuestion(payload);
  } else if (payload.type === "approval") {
    showApproval(payload);
  } else if (payload.type === "done") {
    collected.itinerary = payload.itinerary || collected.itinerary || "";
    collected.final_response = payload.final_response || "";
    collected.llm_calls = payload.llm_calls || 0;
    showResults();
  } else if (payload.type === "error") {
    showError(payload.message);
  }
}

/* ── Human-in-the-loop: question (e.g. missing origin) ── */
function showQuestion(payload) {
  let card = document.getElementById("card-question");
  if (!card) {
    card = document.createElement("div");
    card.className = "agent-card running";
    card.id = "card-question";
    agentsEl.appendChild(card);
  }
  card.innerHTML = `
    <div class="agent-header">❓ Question
      <span class="status running">Waiting for you</span>
    </div>
    <div class="agent-body">
      <p><strong>${payload.question}</strong></p>
      <textarea id="answerInput" rows="1" placeholder="Type your answer…"></textarea>
      <div class="approval-actions">
        <button class="approve-btn" onclick="submitAnswer('${payload.thread_id}')">📩 Send &amp; continue</button>
      </div>
    </div>`;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function submitAnswer(threadId) {
  const origin = document.getElementById("answerInput")?.value.trim();
  if (!origin) return;
  const card = document.getElementById("card-question");
  if (card) {
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    const status = card.querySelector(".status");
    if (status) { status.className = "status running"; status.textContent = "⏳ Continuing…"; }
  }
  try {
    const res = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, origin }),
    });
    if (!res.ok || !res.body) throw new Error("Server returned " + res.status);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const rawEvent = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of rawEvent.split("\n")) {
          if (!line.startsWith("data:")) continue;
          handleEvent(JSON.parse(line.slice(5).trim()));
        }
      }
    }
  } catch (err) {
    showError(err.message);
    if (card) card.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

/* ── Human-in-the-loop approval ── */
function showApproval(payload) {
  collected.itinerary = payload.itinerary || "";
  const card = ensureCard("human_approval");
  card.classList.remove("running");
  card.classList.add("done");
  card.querySelector(".status").className = "status done";
  card.querySelector(".status").textContent = "Waiting for you";

  const body = card.querySelector(".agent-body");
  body.classList.remove("skeleton");
  body.innerHTML = `
    <p><strong>📝 Draft itinerary ready — please review:</strong></p>
    <div class="approval-draft">${renderMd(collected.itinerary || "_No draft available_")}</div>
    <textarea id="feedback" rows="2" placeholder="What should change? (required to reject)"></textarea>
    <div class="approval-actions">
      <button class="approve-btn" onclick="submitApproval('${payload.thread_id}', true)">✅ Approve</button>
      <button class="reject-btn" id="rejectBtn" disabled title="Write feedback first">❌ Reject &amp; revise</button>
    </div>`;
  const feedbackEl = document.getElementById("feedback");
  const rejectBtn = document.getElementById("rejectBtn");
  feedbackEl.addEventListener("input", () => {
    rejectBtn.disabled = feedbackEl.value.trim().length === 0;
  });
  card.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function submitApproval(threadId, approved) {
  const feedback = document.getElementById("feedback")?.value || "";
  const card = document.getElementById("card-human_approval");
  if (card) {
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    const status = card.querySelector(".status");
    if (status) { status.className = "status running"; status.textContent = "⏳ Revising plan…"; }
  }
  try {
    const res = await fetch("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, approved, feedback }),
    });
    if (!res.ok || !res.body) throw new Error("Server returned " + res.status);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const rawEvent = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of rawEvent.split("\n")) {
          if (!line.startsWith("data:")) continue;
          handleEvent(JSON.parse(line.slice(5).trim()));
        }
      }
    }
  } catch (err) {
    showError(err.message);
    if (card) card.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

function completeAgent(node, text) {
  const card = document.getElementById("card-" + node);
  if (!card) return;
  card.classList.remove("running");
  card.classList.add("done");
  card.querySelector(".status").className = "status done";
  card.querySelector(".status").textContent = "Done";

  const body = card.querySelector(".agent-body");
  body.classList.remove("skeleton");
  if (text) {
    body.innerHTML = `<div class="agent-md">${renderMd(text)}</div>`;
  } else {
    body.innerHTML = `<pre class="placeholder">No data returned.</pre>`;
  }
}

/* LLM output -> sanitized HTML (marked renders markdown, DOMPurify strips scripts) */
function renderMd(text) {
  const html = marked.parse(text);
  return window.DOMPurify ? DOMPurify.sanitize(html) : html;
}

function showResults() {
  document.getElementById("mAgents").textContent = agentsEl.querySelectorAll(".done").length;
  document.getElementById("mCalls").textContent = collected.llm_calls;
  metricsEl.classList.remove("hidden");

  const finalText = collected.final_response || collected.itinerary;
  if (finalText) {
    finalCard.innerHTML = renderMd(finalText);
    finalEl.classList.remove("hidden");
    finalEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function showError(message) {
  const card = document.createElement("div");
  card.className = "agent-card running";
  card.style.borderColor = "rgba(255, 90, 90, 0.5)";
  const body = document.createElement("div");
  body.className = "agent-body";
  body.style.color = "#ff9c9c";
  body.textContent = "❌ Error: " + message;
  card.appendChild(body);
  agentsEl.appendChild(card);
}

/* ── Download plan ── */
dlBtn.addEventListener("click", () => {
  const now = new Date();
  const stamp = now.toISOString().replace(/[:T]/g, "-").slice(0, 16);
  const content = `# Travel Plan
**Query:** ${userQuery}
**Generated:** ${now.toLocaleString()}
**User ID:** ${threadEl.value.trim() || "web_user"}

---

## ✈️ Flight Information
${collected.flight_results || "N/A"}

---

## 🏨 Hotel Information
${collected.hotel_results || "N/A"}

---

## 🧠 Final Travel Plan
${collected.final_response || collected.itinerary || "N/A"}

---
*LLM Calls: ${collected.llm_calls}*
`;
  const blob = new Blob([content], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `travel_plan_${stamp}.md`;
  a.click();
  URL.revokeObjectURL(url);
});
