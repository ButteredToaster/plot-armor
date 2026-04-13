/* =====================================================================
   Plot Armor — Frontend
   ===================================================================== */

marked.setOptions({ breaks: true, gfm: true });

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let allComments = [];
let cutoffTimestamp = null;   // Unix seconds; null = show all
let cutoffDateStr = "";       // "YYYY-MM-DD" for display
let showSuggestionTimeout = null;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const $ = id => document.getElementById(id);
const threadUrlInput  = $("thread-url");
const showNameInput   = $("show-name");
const seasonInput     = $("season");
const episodeInput    = $("episode");
const cutoffDateInput = $("cutoff-date");
const loadBtn         = $("load-btn");
const statusEl        = $("status");
const threadSection   = $("thread-section");
const postHeader      = $("post-header");
const filterBar       = $("filter-bar");
const commentsEl      = $("comments-container");
const episodeResult   = $("episode-result");
const showSuggestions = $("show-suggestions");

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
    tab.classList.add("active");
    $(`tab-${tab.dataset.tab}`).classList.remove("hidden");
  });
});

// ---------------------------------------------------------------------------
// Show name autocomplete
// ---------------------------------------------------------------------------
showNameInput.addEventListener("input", () => {
  clearTimeout(showSuggestionTimeout);
  const q = showNameInput.value.trim();
  if (q.length < 2) { hideSuggestions(); return; }
  showSuggestionTimeout = setTimeout(() => fetchShowSuggestions(q), 350);
});

document.addEventListener("click", e => {
  if (!e.target.closest(".field")) hideSuggestions();
});

async function fetchShowSuggestions(q) {
  try {
    const res = await fetch(`/api/search-show?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    if (!Array.isArray(data) || !data.length) { hideSuggestions(); return; }
    showSuggestions.innerHTML = data.map(s => `
      <div class="suggestion-item" data-name="${escHtml(s.name)}">
        <span>${escHtml(s.name)}</span>
        <span class="suggestion-year">${s.firstAired ? s.firstAired.slice(0, 4) : ""}</span>
      </div>
    `).join("");
    showSuggestions.querySelectorAll(".suggestion-item").forEach(item => {
      item.addEventListener("click", () => {
        showNameInput.value = item.dataset.name;
        hideSuggestions();
      });
    });
    showSuggestions.classList.remove("hidden");
  } catch (_) { hideSuggestions(); }
}

function hideSuggestions() {
  showSuggestions.classList.add("hidden");
  showSuggestions.innerHTML = "";
}

// ---------------------------------------------------------------------------
// Load button
// ---------------------------------------------------------------------------
loadBtn.addEventListener("click", async () => {
  const url = threadUrlInput.value.trim();
  if (!url) { showStatus("Please enter a Reddit thread URL.", "error"); return; }

  const activeTab = document.querySelector(".tab.active").dataset.tab;

  // Resolve cutoff date
  if (activeTab === "episode") {
    const show = showNameInput.value.trim();
    const season = seasonInput.value.trim();
    const ep = episodeInput.value.trim();

    if (!show || !season || !ep) {
      showStatus("Please enter show name, season, and episode.", "error");
      return;
    }

    showStatus('<span class="spinner"></span> Looking up episode air date…', "loading");
    const episodeData = await lookupNextEpisode(show, season, ep);
    if (!episodeData) return; // error already shown

    if (episodeData.cutoffDate) {
      cutoffDateStr = episodeData.cutoffDate;
      cutoffTimestamp = dateStrToTimestamp(cutoffDateStr);
      showEpisodeResult(
        `Filtering to before <strong>${episodeData.nextEpisode}</strong> of ` +
        `<strong>${episodeData.showName}</strong> (aired ${cutoffDateStr})`
      );
    } else {
      // Series finale — no filter
      cutoffTimestamp = null;
      cutoffDateStr = "";
      showEpisodeResult(episodeData.message || "No further episodes — showing all comments.", false);
    }

  } else {
    const d = cutoffDateInput.value;
    if (!d) { showStatus("Please select a cutoff date.", "error"); return; }
    cutoffDateStr = d;
    cutoffTimestamp = dateStrToTimestamp(d);
  }

  // Fetch the thread
  showStatus('<span class="spinner"></span> Loading thread…', "loading");
  loadBtn.disabled = true;

  try {
    const res = await fetch(`/api/thread?url=${encodeURIComponent(url)}`);
    const data = await res.json();

    if (data.error) { showStatus("Error: " + data.error, "error"); loadBtn.disabled = false; return; }

    allComments = data.comments;
    renderPost(data.post);
    renderFilterBar(data.comments);
    renderComments(data.comments);

    threadSection.classList.remove("hidden");
    hideStatus();
    threadSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showStatus("Failed to load thread. Check the URL and try again.", "error");
  }

  loadBtn.disabled = false;
});

// ---------------------------------------------------------------------------
// Episode lookup
// ---------------------------------------------------------------------------
async function lookupNextEpisode(show, season, episode) {
  try {
    const res = await fetch(
      `/api/episode?show=${encodeURIComponent(show)}&season=${season}&episode=${episode}`
    );
    const data = await res.json();
    if (data.error) { showStatus("Error: " + data.error, "error"); return null; }
    return data;
  } catch (_) {
    showStatus("Failed to look up episode. Try entering a date instead.", "error");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function renderPost(post) {
  const date = formatDate(post.created_utc);
  postHeader.innerHTML = `
    <div class="post-meta">
      <span class="post-subreddit">r/${escHtml(post.subreddit)}</span>
      <span>·</span>
      <span>Posted by u/${escHtml(post.author)}</span>
      <span>·</span>
      <span>${date}</span>
      <span class="post-score">▲ ${formatScore(post.score)}</span>
    </div>
    <div class="post-title">${escHtml(post.title)}</div>
    ${post.selftext ? `<div class="post-selftext">${escHtml(post.selftext)}</div>` : ""}
  `;
}

function renderFilterBar(comments) {
  const total = countComments(comments);
  const visible = countVisible(comments, cutoffTimestamp);
  const hidden = total - visible;

  const label = cutoffTimestamp
    ? `Showing comments before <span class="filter-bar-value">${cutoffDateStr}</span>`
    : `Showing all comments`;

  filterBar.innerHTML = `
    <span class="filter-bar-label">${label}</span>
    <span class="filter-stats">${visible} shown${hidden > 0 ? ` · ${hidden} hidden` : ""}</span>
  `;
}

function renderComments(comments, container = commentsEl, depth = 0) {
  if (depth === 0) {
    commentsEl.innerHTML = "";

    const spoilerCount = countHidden(comments, cutoffTimestamp);
    if (spoilerCount > 0) {
      const banner = document.createElement("div");
      banner.className = "spoiler-banner";
      banner.textContent = `🛡️ ${spoilerCount} comment${spoilerCount !== 1 ? "s" : ""} hidden — posted after your cutoff date.`;
      commentsEl.appendChild(banner);
    }

    container = commentsEl;
  }

  for (const comment of comments) {
    const isSpoiler = cutoffTimestamp && comment.created_utc >= cutoffTimestamp;

    if (isSpoiler) continue; // hide spoiler comment and all its replies

    const el = document.createElement("div");
    el.className = `comment depth-${Math.min(depth, 5)}`;
    el.innerHTML = buildCommentHTML(comment, depth);
    container.appendChild(el);

    if (comment.replies && comment.replies.length > 0) {
      renderComments(comment.replies, container, depth + 1);
    }
  }
}

function buildCommentHTML(comment, depth) {
  const date = formatDate(comment.created_utc);
  const authorClass = comment.author === "[deleted]" ? " deleted" : "";
  const bodyHtml = renderMarkdown(comment.body);

  return `
    <div class="comment-meta">
      <span class="comment-author${authorClass}">${escHtml(comment.author)}</span>
      <span class="comment-score">▲ ${formatScore(comment.score)}</span>
      <span class="comment-time">${date}</span>
    </div>
    <div class="comment-body">${bodyHtml}</div>
  `;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function renderMarkdown(text) {
  if (!text || text === "[deleted]" || text === "[removed]") {
    return `<em style="color:var(--text-muted)">${escHtml(text || "")}</em>`;
  }
  return marked.parse(text);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDate(utcSeconds) {
  const d = new Date(utcSeconds * 1000);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatScore(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

// "YYYY-MM-DD" → Unix timestamp at midnight UTC
function dateStrToTimestamp(dateStr) {
  return Date.parse(dateStr + "T00:00:00Z") / 1000;
}

function countComments(comments) {
  let n = 0;
  for (const c of comments) {
    n++;
    if (c.replies) n += countComments(c.replies);
  }
  return n;
}

function countVisible(comments, cutoff) {
  let n = 0;
  for (const c of comments) {
    if (!cutoff || c.created_utc < cutoff) {
      n++;
      if (c.replies) n += countVisible(c.replies, cutoff);
    }
  }
  return n;
}

function countHidden(comments, cutoff) {
  if (!cutoff) return 0;
  return countComments(comments) - countVisible(comments, cutoff);
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------
function showStatus(html, type) {
  statusEl.innerHTML = html;
  statusEl.className = `status ${type}`;
}

function hideStatus() {
  statusEl.className = "status hidden";
}

function showEpisodeResult(html, isError = false) {
  episodeResult.innerHTML = html;
  episodeResult.className = `episode-result${isError ? " error" : ""}`;
  episodeResult.classList.remove("hidden");
}
