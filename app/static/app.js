"use strict";

const icons = {
  shield: '<path d="m12 3 8 3v6c0 5-4 8-8 10-4-2-8-5-8-10V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  sparkles: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 3v4M18 5h4"/>',
  folder: '<path d="M3 7V5h6l2 2h10v12H3z"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  "chevron-down": '<path d="m7 10 5 5 5-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  "arrow-up-right": '<path d="M6 18 18 6M6 6h12v12"/>',
  "arrow-up": '<path d="m6 11 6-6 6 6M12 5v14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  heart: '<path d="M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" transform="translate(0 -2) scale(1 .95)"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  clipboard: '<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12h6M9 16h4"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor" stroke="none"/><circle cx="15" cy="17" r="3" fill="currentColor" stroke="none"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4 2c-1 .5-1.5 1-1.5 2M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  file: '<path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h5"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  quote: '<path d="M10 5H3v7h5c0 4-2 5-5 6v2c5-1 7-4 7-9zm11 0h-7v7h5c0 4-2 5-5 6v2c5-1 7-4 7-9z"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/>',
  chat: '<path d="M21 4H3v13h4v4l5-4h9z"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  x: '<path d="m6 6 12 12M6 18 18 6"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const icon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const state = {documents: [], history: [], conversation: [], current: null, status: null, busy: false, uploading: false, view: "assistant"};

function paintIcons(root = document) {
  $$('[data-icon]', root).forEach(node => { node.innerHTML = icon(node.dataset.icon); });
}

async function api(path, options = {}) {
  const response = await fetch(path, {...options, signal: AbortSignal.timeout(85000)});
  if (!response.ok) {
    let message = "The request could not be completed. Please try again.";
    try {
      const body = await response.json();
      message = Array.isArray(body.detail) ? body.detail.map(item => item.msg).join(" ") : body.detail || message;
    } catch { /* Keep a useful, readable fallback. */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function toast(message, error = false, duration = 5000) {
  const element = document.createElement("div");
  element.className = `toast${error ? " error" : ""}`;
  element.textContent = message;
  $("#toast-region").append(element);
  if (duration) setTimeout(() => element.remove(), duration);
  return element;
}

function formatSize(size) {
  return size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function locationLabel(source) {
  return `${source.filename.toLowerCase().endsWith(".pdf") ? `Page ${source.page} · ` : ""}${source.section}`;
}

function modeLabel(mode) {
  return {extractive: "Source excerpts", openai: "OpenAI answer", ollama: "Local model answer", no_evidence: "No supporting evidence"}[mode] || mode;
}

function setView(view) {
  state.view = view;
  $("#assistant-view").classList.toggle("hidden", view !== "assistant");
  $("#documents-view").classList.toggle("hidden", view !== "documents");
  $$('[data-view]').forEach(button => button.classList.toggle("active", button.dataset.view === view));
  $("#page-label").textContent = view === "assistant" ? "AI assistant" : "Knowledge base";
  $("#page-title").innerHTML = view === "assistant" ? "A little clarity.<br>A lot more <em>peace of mind.</em>" : "Your documents.<br>A world of <em>understanding.</em>";
  $("#page-description").textContent = view === "assistant" ? "Turn complex policy documents into answers you can understand." : "A single home for the policies behind every answer.";
  $("#sidebar").classList.remove("mobile-open");
  $("#mobile-menu").setAttribute("aria-expanded", "false");
}

function renderDocuments() {
  const documents = state.documents;
  ["#nav-document-count", "#knowledge-count", "#library-count"].forEach(id => { $(id).textContent = documents.length; });
  $("#document-list").innerHTML = documents.length ? documents.slice(0, 5).map(doc => `
    <button class="compact-document" data-document="${doc.id}" title="Read ${escapeHTML(doc.title)}">
      <span class="file-icon ${doc.category.toLowerCase()}">${icon("file")}</span><span><strong>${escapeHTML(doc.title)}</strong><small>${escapeHTML(doc.category)} · ${doc.chunk_count} passages${doc.is_demo ? " · Sample" : ""}</small></span><span class="status-dot" title="Indexed"></span>
    </button>`).join("") : '<p class="empty-documents">Add a policy to start asking questions.</p>';
  const scope = $("#document-scope");
  const selected = scope.value;
  scope.innerHTML = '<option value="">All documents</option>' + documents.map(doc => `<option value="${doc.id}">${escapeHTML(doc.title)}</option>`).join("");
  if (documents.some(doc => doc.id === selected)) scope.value = selected;
  const category = $("#category-filter").value;
  const visible = documents.filter(doc => !category || doc.category === category);
  $("#library-summary").textContent = `${visible.length} document${visible.length === 1 ? "" : "s"}${category ? ` · ${category}` : " in your knowledge base"}`;
  $("#library-grid").innerHTML = visible.length ? visible.map(doc => `
    <article class="document-card"><div class="document-card-top"><span class="file-icon ${doc.category.toLowerCase()}">${icon("file")}</span><span class="document-tag">${doc.is_demo ? "Sample · " : ""}${escapeHTML(doc.category)}</span></div>
      <h3>${escapeHTML(doc.title)}</h3><span class="filename" title="${escapeHTML(doc.filename)}">${escapeHTML(doc.filename)}</span>
      <div class="document-facts"><span>${formatSize(doc.size)}</span><span>·</span><span>${doc.chunk_count} passages</span><span>·</span><span>Indexed</span></div>
      <div class="document-actions"><button data-document="${doc.id}">Read document</button><button data-scope="${doc.id}">Ask a question</button><button class="icon-button" data-delete="${doc.id}" aria-label="Remove ${escapeHTML(doc.title)}" title="Remove document">${icon("trash")}</button></div>
    </article>`).join("") : '<div class="library-empty">No documents here yet. Upload a policy to get started.</div>';
}

function renderHistory() {
  $("#recent-list").innerHTML = state.history.length ? state.history.slice(0, 9).map(record => `
    <button class="recent-question" data-history="${record.id}" title="${escapeHTML(record.question)}"><span>${icon("chat")}</span><span>${escapeHTML(record.question)}</span></button>
  `).join("") : '<p class="sidebar-empty">Your conversations will appear here.</p>';
  $("#clear-history").disabled = !state.history.length || state.busy;
}

function answerMarkup(record) {
  return escapeHTML(record.answer)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d+)\]/g, (match, number) => record.sources.some(source => source.citation === Number(number))
      ? `<button class="citation" data-record="${record.id}" data-citation="${number}" aria-label="Open source ${number}">${number}</button>` : match);
}

function renderConversation() {
  const container = $("#conversation");
  container.innerHTML = state.conversation.map(record => `
    <div class="chat-message"><div class="question-bubble">${escapeHTML(record.question)}</div></div>
    <article class="chat-message"><div class="answer-label"><span class="assistant-badge">${icon("sparkles")}</span>PolicyLens<span>${escapeHTML(modeLabel(record.mode))}</span></div>
      ${record.notice ? `<p class="answer-notice">${escapeHTML(record.notice)}</p>` : ""}
      <div class="answer-content">${answerMarkup(record)}</div>
      ${record.sources.some(source => source.is_demo) ? '<p class="answer-demo">Includes fictional sample policy information.</p>' : ""}
      <div class="answer-metadata"><span>${record.sources.length} source passage${record.sources.length === 1 ? "" : "s"}</span><span>·</span><span>${record.latency_ms < 1000 ? `${record.latency_ms} ms` : `${(record.latency_ms / 1000).toFixed(1)} s`}</span><button data-copy="${record.id}">${icon("copy")}Copy answer</button></div>
    </article>`).join("");
  if (state.busy) {
    const pending = document.createElement("div");
    pending.className = "chat-message question-bubble";
    pending.textContent = state.pendingQuestion;
    container.append(pending);
    container.insertAdjacentHTML("beforeend", '<div class="loading-message"><span class="loading-dots"><i></i><i></i><i></i></span>Finding the relevant policy passages…</div>');
  }
  const hasConversation = state.conversation.length > 0 || state.busy;
  $("#welcome").classList.toggle("hidden", hasConversation);
  container.classList.toggle("hidden", !hasConversation);
  container.scrollTop = container.scrollHeight;
}

function renderSources(record) {
  state.current = record;
  const sources = record?.sources || [];
  $("#sources-card").classList.toggle("hidden", sources.length === 0);
  $("#how-card").classList.toggle("hidden", sources.length > 0);
  $("#source-list").innerHTML = sources.map(source => `
    <details class="source-item" id="source-${source.citation}" ${source.citation === 1 ? "open" : ""}><summary><span class="source-number">${source.citation}</span><span><strong>${escapeHTML(source.title)}</strong><small>${escapeHTML(locationLabel(source))}</small></span></summary><div class="source-text">${escapeHTML(source.text)}</div><div class="source-actions"><button class="text-button" data-document="${source.document_id}">Read full document</button></div></details>
  `).join("");
}

async function refresh() {
  const [documents, history, status] = await Promise.all([api("/api/documents"), api("/api/history"), api("/api/status")]);
  state.documents = documents;
  state.history = history;
  state.status = status;
  renderDocuments();
  renderHistory();
  const badge = $("#mode-badge");
  badge.innerHTML = `<span class="status-dot"></span>${status.provider === "extractive" ? "Evidence mode" : status.provider === "ollama" ? "Local model" : status.provider === "openai" ? "OpenAI model" : "Check model settings"}`;
  $(".system-status").innerHTML = '<span class="status-dot"></span>Workspace ready';
}

async function submitQuestion(event) {
  event?.preventDefault();
  if (state.busy) return;
  const question = $("#question").value.trim();
  if (question.length < 3) {
    toast("Enter a question with at least 3 characters.", true);
    $("#question").focus();
    return;
  }
  if (!state.documents.length) { toast("Add a document before asking a question.", true); return; }
  state.busy = true;
  state.pendingQuestion = question;
  $("#send-button").disabled = true;
  $("#new-question").disabled = true;
  $("#clear-history").disabled = true;
  renderConversation();
  try {
    const scope = $("#document-scope").value;
    const record = await api("/api/ask", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question, document_ids: scope ? [scope] : [], top_k: 5})});
    state.conversation.push(record);
    state.history.unshift(record);
    state.history = state.history.slice(0, 50);
    $("#question").value = "";
    renderSources(record);
  } catch (error) {
    toast(error.name === "TimeoutError" ? "The request timed out. Check the model service and try again." : error.message, true, 8000);
  } finally {
    state.busy = false;
    $("#send-button").disabled = false;
    $("#new-question").disabled = false;
    renderConversation();
    renderHistory();
    $("#question").focus({preventScroll: true});
  }
}

async function uploadFiles(files) {
  if (state.uploading) { toast("Please wait for the current upload to finish."); return; }
  if (!files.length) return;
  state.uploading = true;
  const progress = toast(`Indexing ${files.length} document${files.length === 1 ? "" : "s"}…`, false, 0);
  let added = 0, duplicates = 0;
  try {
    for (const file of files) {
      if (file.size > 15 * 1024 * 1024) { toast(`${file.name}: maximum file size is 15 MB.`, true); continue; }
      if (!/\.(pdf|docx|txt|md)$/i.test(file.name)) { toast(`${file.name}: choose a PDF, DOCX, TXT, or MD file.`, true); continue; }
      progress.textContent = `Indexing ${file.name}…`;
      const body = new FormData();
      body.append("file", file);
      try {
        const result = await api("/api/documents", {method: "POST", body});
        if (result.duplicate) duplicates++; else added++;
      } catch (error) { toast(`${file.name}: ${error.message}`, true, 7000); }
    }
    await refresh();
    if (added || duplicates) toast(`${added} document${added === 1 ? "" : "s"} added${duplicates ? ` · ${duplicates} already indexed` : ""}.`);
  } catch (error) { toast(error.message, true); }
  finally {
    state.uploading = false;
    progress.remove();
    $("#file-input").value = "";
  }
}

function openDialog(title, content, kicker = "POLICYLENS") {
  $("#dialog-title").textContent = title;
  $("#dialog-kicker").textContent = kicker;
  $("#dialog-content").innerHTML = content;
  if (!$("#detail-dialog").open) $("#detail-dialog").showModal();
}

async function openDocument(id) {
  try {
    const doc = await api(`/api/documents/${encodeURIComponent(id)}`);
    openDialog(doc.title, `
      <div class="dialog-facts">${escapeHTML(doc.filename)} · ${doc.chunk_count} passages · ${formatSize(doc.size)}${doc.is_demo ? " · Fictional sample" : ""}</div>
      ${doc.passages.map(passage => `<section class="dialog-passage"><h3>${escapeHTML(locationLabel({...passage, filename: doc.filename}))}</h3><p>${escapeHTML(passage.text)}</p></section>`).join("")}
    `, "DOCUMENT PREVIEW");
  } catch (error) { toast(error.message, true); }
}

function showInfo() {
  const settings = state.status || {};
  openDialog("A clear path from policy to answer.", `
    <p>PolicyLens is a local insurance document assistant. Add PDF, DOCX, Markdown, or text files, then ask questions in plain language.</p>
    <h3>1. Read and index</h3><p>Documents are split into overlapping passages while retaining section headings and PDF page numbers. Documents, passages, and recent questions stay in a local SQLite database.</p>
    <h3>2. Find the evidence</h3><p>BM25 ranks passages using your question’s words and a small insurance vocabulary. Choose “All documents” or a single policy to control what is searched. Each question is searched independently; include the policy and topic in follow-up questions.</p>
    <h3>3. Answer with citations</h3><p>Evidence mode quotes matching passages without an API key. Open a numbered citation to inspect the source. Optional Ollama or OpenAI integration can turn those passages into a generated explanation.</p>
    <h3>Current configuration</h3><p>Answer provider: <code>${escapeHTML(settings.provider || "loading")}</code>${settings.model ? `<br>Model: <code>${escapeHTML(settings.model)}</code>` : ""}<br>Indexed documents: ${settings.documents ?? state.documents.length}<br>Indexed passages: ${settings.chunks ?? "–"}</p>
    <h3>Enable a language model</h3><p>Copy <code>.env.example</code> to <code>.env</code> in the project folder. Set <code>ANSWER_PROVIDER=ollama</code> with a running local model, or set <code>ANSWER_PROVIDER=openai</code>, <code>OPENAI_API_KEY</code>, and <code>OPENAI_MODEL</code>. Restart the server.</p>
    <p>With OpenAI enabled, the selected excerpts and your question are sent to OpenAI. The default evidence mode uses no external service. Ollama uses the server address in your project configuration.</p>
    <h3>About the samples</h3><p>The three included policies are fictional demonstration documents. Model citations are checked for valid source numbers; this does not guarantee that every generated claim is correct. Always check the original terms. Scanned PDFs require OCR before upload.</p>
  `, "HOW IT WORKS · LOCAL EDITION");
}

function findRecord(id) {
  return state.conversation.find(record => record.id === id) || state.history.find(record => record.id === id);
}

function exportConversation() {
  if (!state.conversation.length) { toast("Ask a question first to export your conversation."); return; }
  const content = "# PolicyLens conversation\n\n" + state.conversation.map(record => `## ${record.question}\n\n${record.answer}\n\nMode: ${modeLabel(record.mode)}\n\n` + record.sources.map(source => `### [${source.citation}] ${source.title} — ${locationLabel(source)}\n\n${source.text}${source.is_demo ? "\n\nFictional demonstration policy." : ""}`).join("\n\n")).join("\n\n---\n\n");
  const url = URL.createObjectURL(new Blob([content], {type: "text/markdown;charset=utf-8"}));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "policylens-conversation.md";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.addEventListener("click", async (event) => {
  const view = event.target.closest("[data-view]");
  if (view) setView(view.dataset.view);
  if (event.target.closest("[data-upload]")) $("#file-input").click();
  const suggestion = event.target.closest("[data-question]");
  if (suggestion && !state.busy) {
    $("#question").value = suggestion.dataset.question;
    submitQuestion();
  }
  const documentButton = event.target.closest("[data-document]");
  if (documentButton) openDocument(documentButton.dataset.document);
  const scope = event.target.closest("[data-scope]");
  if (scope) {
    $("#document-scope").value = scope.dataset.scope;
    setView("assistant");
    $("#question").focus();
  }
  const remove = event.target.closest("[data-delete]");
  if (remove) {
    const doc = state.documents.find(document => document.id === remove.dataset.delete);
    if (!doc || !confirm(`Remove “${doc.title}” from the knowledge base? Stored answer snapshots will remain in recent questions.`)) return;
    try {
      await api(`/api/documents/${doc.id}`, {method: "DELETE"});
      await refresh();
      toast("Document removed from the knowledge base.");
    } catch (error) { toast(error.message, true); }
  }
  const recent = event.target.closest("[data-history]");
  if (recent && !state.busy) {
    const record = findRecord(recent.dataset.history);
    if (record) {
      state.conversation = [record];
      setView("assistant");
      renderConversation();
      renderSources(record);
    }
  }
  const citation = event.target.closest("[data-citation]");
  if (citation) {
    const record = findRecord(citation.dataset.record);
    if (!record) return;
    renderSources(record);
    const source = $(`#source-${Number(citation.dataset.citation)}`);
    if (source) {
      source.open = true;
      source.classList.add("highlighted");
      source.scrollIntoView({behavior: "smooth", block: "nearest"});
    }
  }
  const copy = event.target.closest("[data-copy]");
  if (copy) {
    const record = findRecord(copy.dataset.copy);
    if (record) {
      try { await navigator.clipboard.writeText(record.answer); toast("Answer copied."); }
      catch { toast("Clipboard unavailable. You can export the conversation instead.", true); }
    }
  }
  if ($(window.innerWidth <= 700 ? "#sidebar.mobile-open" : ".not-an-element") && !event.target.closest("#sidebar, #mobile-menu")) {
    $("#sidebar").classList.remove("mobile-open");
    $("#mobile-menu").setAttribute("aria-expanded", "false");
  }
});

$("#question-form").addEventListener("submit", submitQuestion);
$("#question").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submitQuestion(); }
});
$("#new-question").addEventListener("click", () => {
  if (state.busy) return;
  state.conversation = [];
  $("#question").value = "";
  setView("assistant");
  renderConversation();
  renderSources(null);
  $("#question").focus({preventScroll: true});
});
$("#file-input").addEventListener("change", event => uploadFiles([...event.target.files]));
$("#category-filter").addEventListener("change", renderDocuments);
$("#clear-history").addEventListener("click", async () => {
  if (state.busy || !confirm("Clear all stored recent questions and answers? Your policy documents will stay in the knowledge base.")) return;
  try {
    await api("/api/history", {method: "DELETE"});
    state.history = [];
    state.conversation = [];
    renderHistory(); renderConversation(); renderSources(null);
    toast("Recent questions cleared.");
  } catch (error) { toast(error.message, true); }
});
$("#close-dialog").addEventListener("click", () => $("#detail-dialog").close());
$("#detail-dialog").addEventListener("click", event => {
  if (event.target === $("#detail-dialog")) {
    const bounds = event.target.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.target.close();
  }
});
["#settings-button", "#mode-badge", "#how-it-works", "#workspace-info"].forEach(id => $(id).addEventListener("click", showInfo));
$("#export-answer").addEventListener("click", exportConversation);
$("#mobile-menu").addEventListener("click", () => {
  const isOpen = $("#sidebar").classList.toggle("mobile-open");
  $("#mobile-menu").setAttribute("aria-expanded", String(isOpen));
});
$("#drop-zone").addEventListener("click", () => $("#file-input").click());
$("#drop-zone").addEventListener("keydown", event => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); $("#file-input").click(); }
});
["dragenter", "dragover"].forEach(type => $("#drop-zone").addEventListener(type, event => {
  event.preventDefault(); event.currentTarget.classList.add("drag-over");
}));
["dragleave", "drop"].forEach(type => $("#drop-zone").addEventListener(type, event => {
  event.preventDefault(); event.currentTarget.classList.remove("drag-over");
}));
$("#drop-zone").addEventListener("drop", event => uploadFiles([...event.dataTransfer.files]));

paintIcons();
refresh().catch(error => {
  $(".system-status").textContent = "Connection unavailable";
  $("#document-list").innerHTML = '<p class="empty-documents">Could not load your documents. Check that the server is running and reload.</p>';
  toast(error.message, true, 9000);
});
