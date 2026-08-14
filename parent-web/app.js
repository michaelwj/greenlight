const $ = (sel) => document.querySelector(sel);
const TOKEN_KEY = "fa_parent_token";

let token = localStorage.getItem(TOKEN_KEY) || "";

// ---------- API ----------

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    setLoggedIn(false);
    throw new Error("Session expired — sign in again.");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

const get = (path) => api(path);
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const put = (path, body) => api(path, { method: "PUT", body: JSON.stringify(body || {}) });
const del = (path) => api(path, { method: "DELETE" });

// ---------- UI helpers ----------

let toastTimer;
function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.style.borderColor = isError ? "var(--bad)" : "var(--panel-border)";
  node.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), 3500);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function minutesLabel(seconds) {
  if (!seconds) return "?";
  return `${Math.ceil(seconds / 60)} min`;
}

function statusChip(item) {
  const map = {
    approved: ["ok", "approved"],
    available: ["ok", "on plex"],
    downloading: ["ok", "downloading"],
    needs_review: ["warn", "needs review"],
    analyzing: ["warn", "analyzing"],
    submitted: ["warn", "submitted"],
    rejected: ["bad", "denied"],
    failed: ["bad", "failed"],
    removed: ["", "removed"],
  };
  const [cls, label] = map[item.status] || ["", item.status];
  return `<span class="chip ${cls}">${label}</span>`;
}

// ---------- Auth ----------

function setLoggedIn(loggedIn) {
  $("#loginPanel").classList.toggle("hidden", loggedIn);
  $("#appPanels").classList.toggle("hidden", !loggedIn);
  if (!loggedIn) {
    localStorage.removeItem(TOKEN_KEY);
    token = "";
  }
}

$("#loginBtn").addEventListener("click", async () => {
  token = $("#tokenInput").value.trim();
  if (!token) return toast("Paste a token first", true);
  try {
    await get("/api/youtube-requests/pending");
    localStorage.setItem(TOKEN_KEY, token);
    setLoggedIn(true);
    renderReview();
  } catch (err) {
    toast(err.message, true);
  }
});

$("#logoutBtn").addEventListener("click", () => setLoggedIn(false));

// ---------- Tabs ----------

const renderers = {
  review: renderReview,
  history: renderHistory,
  kids: renderKids,
  channels: renderChannels,
  digest: renderDigest,
  settings: renderSettings,
};

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".tabpane").forEach((pane) => pane.classList.add("hidden"));
    const name = tab.dataset.tab;
    $(`#tab-${name}`).classList.remove("hidden");
    renderers[name]();
  });
});

// ---------- Review ----------

// Maintenance actions by status: kill anything stuck in the pipeline, retry
// failed downloads without re-screening. "remove" frees the duplicate check
// so the same video can be requested again.
function maintenanceButtons(item) {
  const buttons = [];
  if (item.status === "failed" || item.status === "downloading") {
    buttons.push(`<button data-action="retry-download" class="secondary">Retry download</button>`);
  }
  if (item.status === "available") {
    // For when the file was deleted from the Plex library by hand.
    buttons.push(`<button data-action="retry-download" class="secondary">Re-download</button>`);
  }
  if (item.status === "failed" || item.status === "analyzing" || item.status === "submitted") {
    buttons.push(`<button data-action="recheck" class="secondary">Re-run check</button>`);
  }
  if (item.status === "rejected") {
    buttons.push(`<button data-action="approve">Approve anyway</button>`);
  }
  if (item.status !== "removed" && item.status !== "available") {
    buttons.push(`<button data-action="remove" class="ghost">Remove</button>`);
  }
  return buttons.join("");
}

function requestCard(item, { showActions }) {
  const concerns = (item.ai_concerns || []).map(escapeHtml).join(", ");
  const transcript = item.transcript_text ? "" : "";
  return `
    <div class="card" data-id="${item.id}">
      ${item.thumbnail_url ? `<img class="thumb" src="${escapeHtml(item.thumbnail_url)}" alt="" />` : ""}
      <h3>${escapeHtml(item.title || item.youtube_url)}</h3>
      <div class="meta">
        ${escapeHtml(item.channel_name || "unknown channel")} · ${minutesLabel(item.duration_seconds)}
        · ${escapeHtml(item.classified_category || "?")} (${item.allowance_bucket || "?"})
      </div>
      <div>
        ${statusChip(item)}
        ${item.requested_by_name ? `<span class="chip kid">👤 ${escapeHtml(item.requested_by_name)}</span>` : ""}
        ${item.decision_source ? `<span class="chip">${item.decision_source}</span>` : ""}
        ${item.minutes_charged ? `<span class="chip">${item.minutes_charged} min charged</span>` : ""}
        ${item.ai_confidence != null ? `<span class="chip">AI ${(item.ai_confidence * 100).toFixed(0)}%</span>` : ""}
      </div>
      ${item.ai_summary ? `<p class="hint">${escapeHtml(item.ai_summary)}</p>` : ""}
      ${
        (item.review_reasons || []).length
          ? `<div class="review-why"><span>Why review?</span><ul>${item.review_reasons
              .map((reason) => `<li>${escapeHtml(reason)}</li>`)
              .join("")}</ul></div>`
          : ""
      }
      ${concerns ? `<p class="hint">Concerns: ${concerns}</p>` : ""}
      ${item.denial_reason ? `<p class="hint">Reason: ${escapeHtml(item.denial_reason)}</p>` : ""}
      <details>
        <summary>Details</summary>
        <pre>${escapeHtml(JSON.stringify(item.hard_rule_results || {}, null, 2))}</pre>
        <p><a href="${escapeHtml(item.youtube_url)}" target="_blank" rel="noreferrer">Open on YouTube</a></p>
      </details>
      ${transcript}
      ${
        showActions
          ? `<div class="actions">
              <button data-action="approve">Approve</button>
              <button data-action="trust" class="secondary">Approve + trust channel</button>
              <button data-action="reject" class="danger">Deny</button>
            </div>`
          : `<div class="actions">${maintenanceButtons(item)}</div>`
      }
    </div>`;
}

function wireRequestActions(pane, rerender) {
  pane.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest(".card").dataset.id;
      const action = button.dataset.action;
      try {
        if (action === "approve") await post(`/api/youtube-requests/${id}/approve`, {});
        if (action === "trust") await post(`/api/youtube-requests/${id}/trust-channel`);
        if (action === "reject") await post(`/api/youtube-requests/${id}/reject`, {});
        if (action === "retry-download") await post(`/api/youtube-requests/${id}/retry-download`);
        if (action === "recheck") await post(`/api/youtube-requests/${id}/retry`);
        if (action === "remove") await post(`/api/youtube-requests/${id}/remove`);
        const messages = {
          approve: "Approved — download queued",
          trust: "Approved — download queued",
          reject: "Denied",
          "retry-download": "Download re-queued",
          recheck: "Re-checking the video",
          remove: "Removed — it can be requested again",
        };
        toast(messages[action] || "Done");
        rerender();
      } catch (err) {
        toast(err.message, true);
      }
    });
  });
}

async function renderReview() {
  const pane = $("#tab-review");
  pane.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const items = await get("/api/youtube-requests/pending");
    if (!items.length) {
      pane.innerHTML = `<div class="panel"><div class="empty">Nothing waiting for review 🎉</div></div>`;
      return;
    }
    pane.innerHTML = items.map((item) => requestCard(item, { showActions: true })).join("");
    wireRequestActions(pane, renderReview);
  } catch (err) {
    pane.innerHTML = `<div class="panel"><div class="empty">${escapeHtml(err.message)}</div></div>`;
  }
}

// ---------- History ----------

async function renderHistory() {
  const pane = $("#tab-history");
  pane.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const items = await get("/api/youtube-requests/history?days=3&limit=100");
    pane.innerHTML = items.length
      ? items.map((item) => requestCard(item, { showActions: false })).join("")
      : `<div class="panel"><div class="empty">No requests in the last 3 days.</div></div>`;
    wireRequestActions(pane, renderHistory);
  } catch (err) {
    pane.innerHTML = `<div class="panel"><div class="empty">${escapeHtml(err.message)}</div></div>`;
  }
}

// ---------- Kids ----------

async function renderKids() {
  const pane = $("#tab-kids");
  pane.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const kids = await get("/api/children");
    if (!kids.length) {
      pane.innerHTML = `<div class="panel"><div class="empty">No children yet — use admin_cli.py create-child.</div></div>`;
      return;
    }
    const cards = await Promise.all(
      kids.map(async (kid) => {
        let budget = null;
        try {
          budget = await get(`/api/children/${kid.id}/budget`);
        } catch {
          /* budget endpoint may 404 if child was deleted mid-flight */
        }
        return `
          <div class="card" data-id="${kid.id}">
            <h3>${escapeHtml(kid.display_name)}</h3>
            ${
              budget
                ? `<div class="meta">Fun-video budget: ${budget.used_minutes}/${budget.weekly_minutes} min used
                   (${budget.remaining_minutes} left this week)</div>`
                : ""
            }
            <div class="row">
              <label>Weekly fun minutes
                <input type="number" class="budget-input" value="${budget ? budget.weekly_minutes : 120}" min="0" />
              </label>
              <label>Requests per day
                <input type="number" class="limit-input" min="0"
                  value="${kid.daily_request_limit ?? ""}" placeholder="default" />
              </label>
              <button data-action="save-kid" class="secondary">Save</button>
            </div>
            <p class="hint">Leave "requests per day" empty to use the household default.</p>
          </div>`;
      })
    );
    pane.innerHTML = cards.join("");

    pane.querySelectorAll("[data-action='save-kid']").forEach((button) => {
      button.addEventListener("click", async () => {
        const card = button.closest(".card");
        const id = card.dataset.id;
        try {
          const minutes = Number(card.querySelector(".budget-input").value);
          await put(`/api/children/${id}/budget`, { weekly_minutes: minutes });
          const rawLimit = card.querySelector(".limit-input").value.trim();
          await put(`/api/children/${id}/request-limit`, {
            daily_request_limit: rawLimit === "" ? null : Number(rawLimit),
          });
          toast("Saved");
          renderKids();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
  } catch (err) {
    pane.innerHTML = `<div class="panel"><div class="empty">${escapeHtml(err.message)}</div></div>`;
  }
}

// ---------- Channels ----------

async function renderChannels() {
  const pane = $("#tab-channels");
  pane.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const rules = await get("/api/channel-rules");
    const rows = rules
      .map(
        (rule) => `
        <div class="card" data-id="${rule.id}">
          <h3>${escapeHtml(rule.channel_name)}</h3>
          <div>
            <span class="chip ${rule.status === "trusted" ? "ok" : "bad"}">${rule.status}</span>
            ${rule.subscribed ? `<span class="chip">subscribed</span>` : ""}
          </div>
          <div class="actions">
            <button data-action="toggle-sub" class="secondary">
              ${rule.subscribed ? "Unsubscribe" : "Subscribe to new uploads"}
            </button>
            <button data-action="delete" class="ghost">Remove</button>
          </div>
        </div>`
      )
      .join("");

    pane.innerHTML = `
      <div class="panel">
        <h2>Add channel rule</h2>
        <label>Channel name <input id="newChannelName" placeholder="Khan Academy" /></label>
        <div class="row">
          <label>Status
            <select id="newChannelStatus">
              <option value="trusted">trusted</option>
              <option value="blocked">blocked</option>
            </select>
          </label>
          <button id="addChannelBtn">Add</button>
        </div>
      </div>
      ${rows || `<div class="panel"><div class="empty">No channel rules yet.</div></div>`}`;

    $("#addChannelBtn").addEventListener("click", async () => {
      const name = $("#newChannelName").value.trim();
      if (!name) return toast("Channel name required", true);
      try {
        await post("/api/channel-rules", { channel_name: name, status: $("#newChannelStatus").value });
        toast("Saved");
        renderChannels();
      } catch (err) {
        toast(err.message, true);
      }
    });

    pane.querySelectorAll(".card [data-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const card = button.closest(".card");
        const id = card.dataset.id;
        const rule = rules.find((r) => r.id === id);
        try {
          if (button.dataset.action === "delete") {
            await del(`/api/channel-rules/${id}`);
            toast("Removed");
          } else {
            await post("/api/channel-rules", {
              channel_name: rule.channel_name,
              channel_id: rule.channel_id,
              status: rule.status,
              subscribed: !rule.subscribed,
            });
            toast(rule.subscribed ? "Unsubscribed" : "Subscribed");
          }
          renderChannels();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
  } catch (err) {
    pane.innerHTML = `<div class="panel"><div class="empty">${escapeHtml(err.message)}</div></div>`;
  }
}

// ---------- Digest ----------

function digestCard(digest) {
  const payload = digest.payload || {};
  const budgets = (payload.budgets || [])
    .map((b) => `<li>${escapeHtml(b.child)}: ${b.used_minutes}/${b.weekly_minutes} fun minutes</li>`)
    .join("");
  const channels = (payload.top_channels || [])
    .map((c) => `<li>${escapeHtml(c.channel)} (${c.count})</li>`)
    .join("");
  const denials = (payload.denials || [])
    .map((d) => `<li>${escapeHtml(d.title)} — ${escapeHtml(d.reason || "")}</li>`)
    .join("");
  const start = new Date(digest.week_start).toLocaleDateString();
  const end = new Date(digest.week_end).toLocaleDateString();
  return `
    <div class="card">
      <h3>Week ${start} – ${end}</h3>
      <p>${escapeHtml(payload.summary_line || "")}</p>
      ${budgets ? `<h4>Budgets</h4><ul>${budgets}</ul>` : ""}
      ${channels ? `<h4>Top channels</h4><ul>${channels}</ul>` : ""}
      ${denials ? `<h4>Denials</h4><ul>${denials}</ul>` : ""}
    </div>`;
}

async function renderDigest() {
  const pane = $("#tab-digest");
  pane.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const digests = await get("/api/digests?limit=8");
    pane.innerHTML = `
      <div class="panel">
        <button id="generateDigestBtn" class="secondary">Generate digest now</button>
      </div>
      ${digests.length ? digests.map(digestCard).join("") : `<div class="panel"><div class="empty">No digest yet — one is generated every week automatically.</div></div>`}`;
    $("#generateDigestBtn").addEventListener("click", async () => {
      try {
        await post("/api/digests/generate");
        toast("Digest generated");
        renderDigest();
      } catch (err) {
        toast(err.message, true);
      }
    });
  } catch (err) {
    pane.innerHTML = `<div class="panel"><div class="empty">${escapeHtml(err.message)}</div></div>`;
  }
}

// ---------- Push notifications ----------

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

async function renderSettings() {
  const status = $("#pushStatus");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    status.textContent = "Push is not supported in this browser. On iOS, add this page to your Home Screen first.";
    return;
  }
  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = registration ? await registration.pushManager.getSubscription() : null;
  status.textContent = subscription ? "Push notifications are enabled on this device." : "Push notifications are off.";
}

$("#enablePushBtn").addEventListener("click", async () => {
  try {
    if (!("serviceWorker" in navigator)) throw new Error("Service workers unsupported");
    const registration = await navigator.serviceWorker.register("./sw.js");
    await navigator.serviceWorker.ready;

    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("Notification permission denied");

    const { public_key } = await get("/api/push/public-key");
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    });
    const json = subscription.toJSON();
    await post("/api/push/subscribe", {
      endpoint: json.endpoint,
      keys: json.keys,
      device_label: navigator.userAgent.slice(0, 100),
    });
    toast("Push enabled");
    renderSettings();
  } catch (err) {
    toast(err.message, true);
  }
});

// ---------- Boot ----------

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(() => {});
}

if (token) {
  setLoggedIn(true);
  renderReview();
} else {
  setLoggedIn(false);
}
