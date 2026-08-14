const el = (id) => document.getElementById(id);

const store = {
  get code() {
    return localStorage.getItem("fa_household_code") || "";
  },
  set code(value) {
    localStorage.setItem("fa_household_code", value);
  },
  get childId() {
    return localStorage.getItem("fa_child_id") || "";
  },
  set childId(value) {
    localStorage.setItem("fa_child_id", value);
  },
};

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Household-Code": el("householdCode").value.trim(),
    ...(options.headers || {}),
  };
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

const STATUS_LABELS = {
  submitted: "⏳ submitted",
  analyzing: "🔍 checking",
  needs_review: "🕐 waiting for a parent",
  approved: "✅ approved",
  downloading: "⬇️ downloading",
  available: "🍿 on Plex!",
  rejected: "❌ not approved",
  failed: "⚠️ something went wrong",
  removed: "🗑️ removed — you can ask again",
};

async function loadChildren() {
  try {
    const children = await request("/api/children");
    const select = el("childSelect");
    select.innerHTML =
      `<option value="">— pick your name —</option>` +
      children.map((child) => `<option value="${child.id}">${child.display_name}</option>`).join("");
    if (store.childId) {
      select.value = store.childId;
    }
  } catch {
    el("childSelect").innerHTML = `<option value="">Could not load kids</option>`;
  }
}

async function refreshBudget() {
  const childId = store.childId;
  if (!childId) return;
  try {
    const budget = await request(`/api/children/${childId}/budget-status`);
    el("budgetLine").textContent =
      `Fun videos: ${budget.remaining_minutes} of ${budget.weekly_minutes} minutes left this week. ` +
      `Learning videos are always free!`;
  } catch {
    el("budgetLine").textContent = "Could not load budget (check household code).";
  }
}

let lastRequests = [];

// A failed/removed request can be asked for again — but only when we still
// have a real video link (invalid-URL failures have no video_id; the kid
// needs to paste a proper link instead). Rejected videos can't be re-asked.
function canReRequest(item) {
  return (item.status === "failed" || item.status === "removed") && Boolean(item.video_id);
}

async function refreshRequests() {
  const childId = store.childId;
  if (!childId) return;
  try {
    const items = await request(`/api/youtube-requests/mine?child_id=${encodeURIComponent(childId)}&limit=25`);
    lastRequests = items;
    if (!items.length) {
      el("requestList").innerHTML = `<p class="footnote">Nothing yet.</p>`;
      return;
    }
    el("requestList").innerHTML = items
      .map((item, index) => {
        const title = item.title || item.youtube_url;
        const label = STATUS_LABELS[item.status] || item.status;
        const reason = item.denial_reason ? `<div class="footnote">${item.denial_reason}</div>` : "";
        const again = canReRequest(item)
          ? `<button class="rerequest" data-idx="${index}">🔁 Ask again</button>`
          : "";
        return `<div class="request-row"><strong>${label}</strong>${title}${reason}${again}</div>`;
      })
      .join("");
  } catch {
    /* keep last list on transient errors */
  }
}

el("requestList").addEventListener("click", async (event) => {
  const button = event.target.closest(".rerequest");
  if (!button) return;
  const item = lastRequests[Number(button.dataset.idx)];
  if (!item || button.disabled) return;
  button.disabled = true;
  button.textContent = "Asking…";
  try {
    await request("/api/youtube-requests", {
      method: "POST",
      body: JSON.stringify({
        requested_by_child_id: store.childId,
        youtube_url: item.youtube_url,
        requested_category: item.requested_category || null,
      }),
    });
    refreshBudget();
    refreshRequests();
  } catch (err) {
    button.disabled = false;
    button.textContent = `Error: ${err.message} — tap to retry`;
  }
});

el("householdCode").value = store.code;

el("householdCode").addEventListener("change", () => {
  store.code = el("householdCode").value.trim();
  refreshBudget();
  refreshRequests();
});

el("childSelect").addEventListener("change", () => {
  store.childId = el("childSelect").value;
  refreshBudget();
  refreshRequests();
});

el("submitYoutube").addEventListener("click", async () => {
  const button = el("submitYoutube");
  if (button.disabled) return;
  const output = el("statusOutput");
  output.classList.remove("hidden");
  button.disabled = true;
  button.textContent = "Checking…";
  try {
    if (!store.childId) throw new Error("Pick your name first");
    const url = el("youtubeUrl").value.trim();
    if (!url) throw new Error("Paste a YouTube URL");

    output.textContent = "Checking the video… this can take a little while.";
    const result = await request("/api/youtube-requests", {
      method: "POST",
      body: JSON.stringify({
        requested_by_child_id: store.childId,
        youtube_url: url,
        requested_category: el("requestedCategory").value.trim() || null,
      }),
    });

    const label = STATUS_LABELS[result.status] || result.status;
    const ageMs = Date.now() - new Date(result.created_at).getTime();
    const prefix = ageMs > 60000 ? "Already requested! " : "";
    output.textContent = result.denial_reason
      ? `${prefix}${label} — ${result.denial_reason}`
      : `${prefix}${label}`;
    el("youtubeUrl").value = "";
    refreshBudget();
    refreshRequests();
  } catch (err) {
    output.textContent = `Error: ${err.message}`;
  } finally {
    button.disabled = false;
    button.textContent = "Submit";
  }
});

loadChildren().then(() => {
  refreshBudget();
  refreshRequests();
});
setInterval(refreshRequests, 30000);
