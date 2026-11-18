"use strict";
const $ = id => document.getElementById(id);
let token = "", state = null, images = [null, null], imageURLs = [null, null], currentVideo = "", sending = false;
let db = null;
let previewSequence = 0, previewTimer = null;

async function api(path, values, retried = false) {
  const response = await fetch(path, {method: values === undefined ? "GET" : "POST", headers: {"X-Studio-Token": token, ...(values === undefined ? {} : {"Content-Type": "application/json"})}, ...(values === undefined ? {} : {body: JSON.stringify(values)})});
  const data = await response.json();
  if (response.status === 403 && !retried) {
    const session = await fetch('/api/session');
    if (session.ok) { token = (await session.json()).token; return api(path, values, true); }
  }
  if (!response.ok) throw new Error(data.error || "Die Anfrage ist fehlgeschlagen.");
  return data;
}
function error(message) { $("form-error").textContent = message; $("form-error").hidden = !message; }
function active() { return state?.job && ["queued", "running", "cancelling"].includes(state.job.state); }
function updateButton() { $("generate").disabled = sending || active() || !state?.ready || state?.setup?.state === "running"; }

function openDB() {
  return new Promise(resolve => {
    const request = indexedDB.open("video-studio-draft", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("pictures");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
  });
}
function readPicture(index) {
  return new Promise(resolve => {
    if (!db) return resolve(null);
    const request = db.transaction("pictures").objectStore("pictures").get(index);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => resolve(null);
  });
}
async function setPicture(index, file, persist = true) {
  if (file && (!/^(image\/jpeg|image\/png|image\/webp)$/.test(file.type) || file.size > 12 * 1024 * 1024)) {
    error("Bitte verwende ein JPG-, PNG- oder WebP-Bild mit höchstens 12 MB."); return;
  }
  const key = index === 0 ? "start" : "end";
  if (imageURLs[index]) URL.revokeObjectURL(imageURLs[index]);
  images[index] = file;
  imageURLs[index] = file ? URL.createObjectURL(file) : null;
  $("preview-" + key).hidden = !file;
  $("empty-" + key).hidden = !!file;
  $("caption-" + key).hidden = !file;
  $("remove-" + key).hidden = !file;
  if (file) $("preview-" + key).src = imageURLs[index];
  else { $("preview-" + key).removeAttribute("src"); $("image-" + key).value = ""; }
  if (persist && db) {
    const store = db.transaction("pictures", "readwrite").objectStore("pictures");
    if (file) store.put(file, index); else store.delete(index);
  }
  schedulePreview();
}
function encode(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("Das Bild konnte nicht gelesen werden.")); reader.readAsDataURL(file);
  });
}
function saveDraft() {
  const values = Object.fromEntries(["scene", "speech", "sounds", "seconds"].map(id => [id, $(id).value]));
  values.direct_prompt = $('direct-prompt').checked;
  try { localStorage.setItem("video-studio-draft", JSON.stringify(values)); } catch (_) { /* Editing works without browser storage. */ }
}
function restoreDraft() {
  try { const draft = JSON.parse(localStorage.getItem("video-studio-draft") || "{}"); for (const id of ["scene", "speech", "sounds", "seconds"]) if (typeof draft[id] === "string") $(id).value = draft[id]; } catch (_) {}
  try { const draft = JSON.parse(localStorage.getItem('video-studio-draft') || '{}'); if (typeof draft.direct_prompt === 'boolean') $('direct-prompt').checked = draft.direct_prompt; } catch (_) {}
}
function promptValues() { return {scene:$('scene').value,speech:$('speech').value,sounds:$('sounds').value,direct_prompt:$('direct-prompt').checked,has_end_image:!!images[1]}; }
function schedulePreview() {
  const sequence = ++previewSequence;
  clearTimeout(previewTimer);
  if (!$('prompt-preview').open) return;
  // Clear stale text immediately; never present an older response as this draft.
  $('prompt-preview-text').value = '';
  $('prompt-preview-text').placeholder = 'Textvorschau wird aktualisiert …';
  previewTimer = setTimeout(async () => {
    try { const result = await api('/api/preview-prompt',promptValues()); if(sequence === previewSequence) {$('prompt-preview-text').value=result.prompt; $('prompt-preview-text').placeholder='Hier erscheint dein Text.';} }
    catch(exc) {if(sequence === previewSequence) $('prompt-preview-text').placeholder=exc.message;}
  },200);
}
$('prompt-preview').addEventListener('toggle',schedulePreview);
function showVideo(url, seconds) {
  if (currentVideo !== url) { $("video").src = url; currentVideo = url; }
  $("video").hidden = false; $("video-placeholder").hidden = true;
  $("download").href = url + "?download=1"; $("download").hidden = false;
  $("result-meta").textContent = `${seconds} Sekunden · MP4`;
}
async function refresh() {
  try {
    const previous = state?.job?.state;
    const next = await api("/api/state");
    if (state && state.version !== next.version) { saveDraft(); location.reload(); return; }
    state = next;
    $("version").textContent = state.version;
    $("update-status").textContent = state.update?.message || 'Automatische Updates aktiv.';
    $("update-footer").textContent = state.update?.message || 'Automatische Updates';
    $("check-updates").disabled = !state.update?.enabled || ['checking','downloading','ready','installing'].includes(state.update?.state);
    const settingUp = state.setup?.state === "running";
    $("setup-panel").hidden = state.ready && !state.setup;
    $("setup-description").textContent = `Einmalig ca. ${state.download_gb} GB KI-Dateien plus Programmbestandteile herunterladen. Danach offline erstellen.`;
    $("setup-help").textContent = `Die erste Einrichtung benötigt Internet und mindestens 65 GB freien Speicher. Die KI-Dateien umfassen ca. ${state.download_gb} GB. Danach erfolgt die Erstellung lokal und offline.`;
    $("setup-start").disabled = settingUp;
    $("setup-start").textContent = settingUp ? "Wird eingerichtet …" : state.ready ? "Erneut prüfen" : "KI einrichten";
    $("setup-message").textContent = state.setup?.message || "";
    $("setup-progress").hidden = !settingUp;
    if (state.setup?.progress != null) $("setup-progress").value = state.setup.progress; else $("setup-progress").removeAttribute("value");
    $("repair").disabled = settingUp || active();
    if (state.setup?.state === "done" && state.ready) $("setup-panel").hidden = true;
    const job = state.job;
    $('submitted-prompt').hidden = !job?.submitted_prompt;
    $('submitted-prompt-text').value = job?.submitted_prompt || '';
    if (job) {
      $("job-status").hidden = false;
      $("job-status").classList.toggle("busy", active());
      $("job-status").classList.toggle("failed", job.state === "error");
      $("job-message").textContent = job.message;
      $("job-progress").hidden = !active();
      if (job.progress != null) $("job-progress").value = job.progress; else $("job-progress").removeAttribute("value");
      $("cancel").hidden = !active(); $("cancel").disabled = job.state === "cancelling";
      $("elapsed").textContent = active() ? `Läuft seit ${Math.floor((Date.now() / 1000 - job.created) / 60)} Min. · Du kannst diese Seite offen lassen.` : "";
      if (job.state === "done") { showVideo(job.video, job.seconds); if (previous !== "done") loadHistory(); }
      else if (active()) { $("download").hidden = true; $("result-meta").textContent = "Wird erstellt"; }
      else { $("result-meta").textContent = currentVideo ? "Gespeichertes Video" : "Vorschau"; }
    }
    updateButton();
  } catch (exc) {
    if (state?.update?.state === 'installing' || state?.update?.state === 'ready') $('update-footer').textContent = 'Aktualisierung läuft. Verbindung wird wiederhergestellt …';
    else error("Verbindung zum lokalen Studio unterbrochen. Starte das Programm bei Bedarf erneut.");
  }
}
async function loadHistory() {
  try {
    const items = await api("/api/history"); $("history-count").textContent = items.length ? `(${items.length})` : "";
    $("history-list").replaceChildren();
    for (const item of items) {
      const button = document.createElement("button"); button.type = "button"; button.className = "history-item";
      const thumbnail = document.createElement("img"); thumbnail.src = `/media/${item.id}/bild-1.jpg`; thumbnail.alt = "";
      const text = document.createElement("span"); text.textContent = new Date(item.created * 1000).toLocaleString("de-DE", {dateStyle:"short",timeStyle:"short"});
      const small = document.createElement("small"); small.textContent = `${item.seconds} Sekunden · Auf deinem PC`; text.append(small);
      button.append(thumbnail, text); button.addEventListener("click", () => { showVideo(item.video, item.seconds); $("video").scrollIntoView({behavior:"smooth",block:"nearest"}); }); $("history-list").append(button);
    }
    if (!items.length) { const p = document.createElement("p"); p.className = "muted small"; p.textContent = "Deine fertigen Videos erscheinen hier."; $("history-list").append(p); }
  } catch (_) {}
}
for (const [index, key] of [[0,"start"],[1,"end"]]) {
  $("image-" + key).addEventListener("change", event => setPicture(index, event.target.files[0] || null));
  $("remove-" + key).addEventListener("click", () => setPicture(index, null));
  const zone = $("upload-" + key);
  zone.addEventListener("dragover", event => {event.preventDefault(); zone.classList.add("dragging");});
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", event => {event.preventDefault(); zone.classList.remove("dragging"); if (event.dataTransfer.files.length) setPicture(index, event.dataTransfer.files[0]);});
}
for (const id of ["scene","speech","sounds","seconds"]) $(id).addEventListener("input", () => {saveDraft(); schedulePreview();});
$('direct-prompt').addEventListener('change',() => {saveDraft(); schedulePreview();});
$("create-form").addEventListener("submit", async event => {
  event.preventDefault(); error("");
  if (!images[0]) {error("Lade zuerst ein Startbild hoch."); $("image-start").focus(); return;}
  sending = true; updateButton(); saveDraft();
  try {
    const values = {...promptValues(),seconds:Number($("seconds").value),images:await Promise.all(images.filter(Boolean).map(encode))};
    await api("/api/generate", values); await refresh();
  } catch (exc) {error(exc.message);} finally {sending = false; updateButton();}
});
$("cancel").addEventListener("click", async () => {try {await api("/api/cancel", {}); await refresh();} catch (exc) {error(exc.message);}});
async function setup() {$("help").close(); error(""); try {await api("/api/setup", {}); await refresh();} catch (exc) {error(exc.message);}}
$("setup-start").addEventListener("click", setup); $("repair").addEventListener("click", setup);
$("check-updates").addEventListener("click", async () => { try {await api('/api/check-updates', {}); await refresh();} catch(exc) {error(exc.message);} });
$("help-open").addEventListener("click", () => $("help").showModal()); $("help-close").addEventListener("click", () => $("help").close());
for (const [id,path] of [["open-folder","/api/open-folder"],["open-log","/api/open-log"]]) $(id).addEventListener("click", async () => {try {await api(path, {});} catch (exc) {$("help").close(); error(exc.message);}});
$("quit").addEventListener("click", async () => {try {await api("/api/quit", {}); document.body.replaceChildren(); const p=document.createElement("p"); p.textContent="Video Studio wurde beendet. Du kannst dieses Fenster schließen."; p.style.padding="40px"; document.body.append(p);} catch(exc) {error(exc.message);}});
async function init() {
  try {
    token = (await api("/api/session")).token;
    restoreDraft(); db = await openDB();
    for (const index of [0,1]) {const file=await readPicture(index); if(file) await setPicture(index,file,false);}
    await refresh(); await loadHistory(); setInterval(refresh, 2500);
  } catch(exc) {error("Das lokale Studio konnte nicht geladen werden. Starte es bitte erneut.");}
}
init();
