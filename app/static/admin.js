"use strict";
/*
 * QR File Share — the app screen.
 *
 * Rules this file keeps:
 *  - Untrusted text (labels, filenames, server messages) is only ever inserted with
 *    textContent, never innerHTML. The page's Content-Security-Policy backs this up.
 *  - No date arithmetic here. Every "until …" sentence comes from the server, so what
 *    the user reads is exactly what gets stored.
 */
(function () {
  const $ = (id) => document.getElementById(id);

  const state = {
    status: null,
    file: null,
    choice: null, // { preset_days } | { until }
    choiceTouched: false, // once the user picks, background refreshes must not override it
    links: [],
    result: null,
    dlg: null, // { mode: "change" | "reactivate", link, choice }
  };

  // ------------------------------------------------------------------- utilities

  async function api(method, url, body, isForm) {
    const opts = { method, credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      if (isForm) {
        opts.body = body;
      } else {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      throw new Error("The app is not responding. Is start.cmd still running?");
    }
    if (res.status === 401) {
      window.location.href = "/admin/login";
      throw new Error("Your session has ended. Please sign in again.");
    }
    const type = res.headers.get("content-type") || "";
    const data = type.includes("application/json") ? await res.json() : null;
    if (!res.ok) {
      const detail = data && data.detail;
      if (typeof detail === "string") throw new Error(detail);
      throw new Error("Something in the form is not valid. Please check it and try again.");
    }
    return data;
  }

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") node.className = v;
        else node.setAttribute(k, v);
      }
    }
    if (text !== undefined) node.textContent = text;
    return node;
  }

  let toastTimer = null;
  function toast(message) {
    const t = $("toast");
    t.textContent = message;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 3200);
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " bytes";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function daysWord(n) {
    return n === 1 ? "1 day" : n + " days";
  }

  function safeFileName(text) {
    return (text || "qr-code").replace(/[\\/:*?"<>|]+/g, " ").trim().slice(0, 80) || "qr-code";
  }

  function qrUrl(id) {
    return "/api/links/" + id + "/qr.png";
  }

  // ------------------------------------------------------------ copy and print

  async function copyImage(id) {
    try {
      if (!window.ClipboardItem || !navigator.clipboard || !navigator.clipboard.write) {
        throw new Error("unsupported");
      }
      const res = await fetch(qrUrl(id), { credentials: "same-origin" });
      if (!res.ok) throw new Error("fetch failed");
      const blob = await res.blob();
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      toast("QR image copied — paste it into WhatsApp, email or Word.");
    } catch (e) {
      toast("This browser blocked copying the image. Use Download PNG instead.");
    }
  }

  async function copyLink(url) {
    try {
      await navigator.clipboard.writeText(url);
      toast("Link copied.");
    } catch (e) {
      toast("Could not copy the link.");
    }
  }

  function openPrint(id) {
    window.open("/admin/print/" + id, "_blank", "noopener");
  }

  // ---------------------------------------------------------------- Drive status

  function renderDrive(status) {
    const d = status.drive;
    const card = $("drive-card");
    const pill = $("drive-pill");
    const btn = $("connect-drive");
    const link = $("drive-signin-link");
    pill.className = "pill";
    card.hidden = false;
    btn.hidden = false;
    link.hidden = true;
    btn.disabled = false;
    btn.textContent = "Connect Google Drive";

    if (d.state === "connected") {
      card.hidden = true;
      pill.classList.add("ok");
      pill.textContent = "Google Drive: " + (d.email || "connected");
      pill.title = pill.textContent;
    } else if (d.state === "connecting") {
      $("drive-card-title").textContent = "Waiting for Google sign-in…";
      // Only ever link to Google's own sign-in page.
      const url = typeof d.sign_in_url === "string" && d.sign_in_url.startsWith("https://accounts.google.com/")
        ? d.sign_in_url : null;
      if (url) {
        // The app cannot open a browser itself (Docker): the user opens Google's page.
        $("drive-card-text").textContent =
          "Click Continue to Google and sign in. Google brings you back when you finish.";
        link.href = url;
        link.hidden = false;
        btn.hidden = true;
      } else {
        $("drive-card-text").textContent =
          "Finish signing in on the Google page that just opened in your browser, then come back here.";
        btn.disabled = true;
        btn.textContent = "Waiting…";
      }
      pill.classList.add("warn");
      pill.textContent = "Google Drive: signing in…";
    } else if (d.state === "not_set_up") {
      $("drive-card-title").textContent = "Google Drive is not set up yet";
      $("drive-card-text").textContent = d.message || "See the setup guide, section 3.";
      btn.hidden = true;
      pill.classList.add("warn");
      pill.textContent = "Google Drive: not set up";
    } else if (d.state === "error") {
      $("drive-card-title").textContent = "Google Drive needs reconnecting";
      $("drive-card-text").textContent = d.message || "Please connect again.";
      pill.classList.add("warn");
      pill.textContent = "Google Drive: reconnect needed";
    } else {
      $("drive-card-title").textContent = "Connect Google Drive";
      $("drive-card-text").textContent =
        "QR codes deliver the PDF from your own Google Drive, so they keep working when this laptop is off. " +
        "Connect once and the app remembers it.";
      pill.classList.add("warn");
      pill.textContent = "Google Drive: not connected";
    }

    // Settings dialog mirror.
    $("settings-drive-text").textContent =
      d.state === "connected"
        ? "Connected as " + (d.email || "your Google account") +
          ". Disconnecting stops expired QR codes being removed until you reconnect; existing QR codes keep working."
        : "Not connected.";
    $("disconnect-drive").hidden = d.state !== "connected";
  }

  function renderSweepWarning(status) {
    const s = status.last_sweep;
    const box = $("sweep-warning");
    if (!s || !s.pending) {
      box.hidden = true;
      return;
    }
    const n = s.pending === 1 ? "1 expired QR code is" : s.pending + " expired QR codes are";
    $("sweep-warning-text").textContent = s.drive_not_connected
      ? n + " still working because Google Drive is not connected. Connect it and they are removed straight away."
      : n + " still working because Google Drive could not be reached. The app keeps retrying every few minutes.";
    box.hidden = false;
  }

  function offsetText(minutes) {
    const sign = minutes >= 0 ? "+" : "-";
    const abs = Math.abs(minutes);
    const h = Math.floor(abs / 60), m = abs % 60;
    return "UTC" + sign + h + (m ? ":" + String(m).padStart(2, "0") : "");
  }

  function renderTimeZone(status) {
    const tz = status.time_zone;
    const docker = status.run_mode === "docker";
    const source = {
      env: "set in the .env file",
      laptop: "taken from the laptop's clock",
      system: docker ? "the container's default — run docker-start.cmd to use the laptop's clock"
                     : "the laptop's clock",
    }[tz.source] || tz.source;
    $("settings-tz-text").textContent =
      "Time limits end at midnight in " + tz.name + " (" + tz.utc_offset_text + "), " + source + ".";

    // The browser runs in the laptop's real zone. If the app counts in another one,
    // "until 5 October" would end at the wrong hour -- say so plainly.
    const laptop = -new Date().getTimezoneOffset();
    const box = $("tz-warning");
    if (laptop === tz.utc_offset_minutes) {
      box.hidden = true;
      return;
    }
    const fix = docker ? "Run docker-start.cmd again to switch."
                       : "Close the black window and run start.cmd again.";
    $("tz-warning-text").textContent =
      "Your laptop is on " + offsetText(laptop) + " but the app is using " + tz.name + " (" +
      tz.utc_offset_text + "), so time limits would end at the wrong hour. " + fix;
    box.hidden = false;
  }

  let statusTimer = null;
  async function loadStatus() {
    clearTimeout(statusTimer);
    try {
      const status = await api("GET", "/api/status");
      const first = state.status === null;
      state.status = status;
      renderDrive(status);
      renderSweepWarning(status);
      renderTimeZone(status);
      configureDateInput($("until"), status.limits);
      if (first) {
        renderPresets();
        renderDefaultSelect();
      }
      updateCreateButton();
      // Poll quickly while a Google sign-in is in progress, slowly otherwise.
      statusTimer = setTimeout(loadStatus, status.drive.state === "connecting" ? 2000 : 60000);
    } catch (e) {
      statusTimer = setTimeout(loadStatus, 10000);
    }
  }

  async function connectDrive() {
    try {
      $("connect-drive").disabled = true;
      await api("POST", "/api/drive/connect");
    } catch (e) {
      toast(e.message);
    }
    loadStatus();
  }

  function configureDateInput(input, limits) {
    input.min = limits.today;
    input.max = limits.max_day;
  }

  // ------------------------------------------------------------------ choosing a file

  function chooseFile(file) {
    $("issue-error").hidden = true;
    if (!file) return;
    const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
    if (!isPdf) {
      showIssueError("That is not a PDF. Only PDF files can be shared.");
      return;
    }
    const max = state.status ? state.status.max_upload_bytes : 25 * 1024 * 1024;
    if (file.size > max) {
      showIssueError("That file is " + formatSize(file.size) + ". The limit is " + formatSize(max) + ".");
      return;
    }
    state.file = file;
    $("chosen-name").textContent = file.name;
    $("chosen-size").textContent = formatSize(file.size);
    $("chosen").hidden = false;
    $("drop").hidden = true;
    updateCreateButton();
  }

  function clearFile() {
    state.file = null;
    $("file-input").value = "";
    $("chosen").hidden = true;
    $("drop").hidden = false;
    updateCreateButton();
  }

  function showIssueError(message) {
    const p = $("issue-error");
    p.textContent = message;
    p.hidden = false;
  }

  // --------------------------------------------------------------- choosing a limit

  function renderPresets() {
    const box = $("presets");
    box.replaceChildren();
    for (const days of state.status.limits.presets) {
      const b = el("button", { class: "chip", type: "button", "aria-pressed": "false" }, daysWord(days));
      b.dataset.days = String(days);
      b.addEventListener("click", () => {
        state.choiceTouched = true;
        setChoice({ preset_days: days });
      });
      box.appendChild(b);
    }
    if (!state.choice) setChoice({ preset_days: state.status.limits.default_preset_days });
  }

  async function setChoice(choice) {
    state.choice = choice;
    for (const b of $("presets").children) {
      b.setAttribute("aria-pressed", String(choice.preset_days === Number(b.dataset.days)));
    }
    if (choice.preset_days !== undefined) $("until").value = "";
    updateCreateButton();
    await previewInto($("limit-sentence"), "/api/limits/preview", choice);
  }

  async function previewInto(target, url, body) {
    target.classList.remove("bad");
    try {
      const out = await api("POST", url, body);
      target.textContent = "✓ " + out.sentence;
      return true;
    } catch (e) {
      target.textContent = e.message;
      target.classList.add("bad");
      return false;
    }
  }

  // ------------------------------------------------------------------- create

  function updateCreateButton() {
    const connected = state.status && state.status.drive.state === "connected";
    const ok = Boolean(connected && state.file && state.choice);
    $("create").disabled = !ok;
    let hint = "";
    if (!connected) hint = "Connect Google Drive to create QR codes.";
    else if (!state.file) hint = "Choose a PDF to continue.";
    $("create-hint").textContent = hint;
  }

  async function createQr() {
    $("issue-error").hidden = true;
    const btn = $("create");
    btn.disabled = true;
    btn.textContent = "Uploading to Google Drive…";
    try {
      const form = new FormData();
      form.append("file", state.file);
      const label = $("label").value.trim();
      if (label) form.append("label", label);
      if (state.choice.preset_days !== undefined) form.append("preset_days", String(state.choice.preset_days));
      else form.append("until", state.choice.until);
      const link = await api("POST", "/api/links", form, true);
      showResult(link);
      loadLinks();
    } catch (e) {
      showIssueError(e.message);
    } finally {
      btn.textContent = "Create QR code";
      updateCreateButton();
    }
  }

  function showResult(link) {
    state.result = link;
    const name = link.label || link.filename;
    $("result-qr").src = qrUrl(link.id) + "?v=" + Date.now();
    $("result-label").textContent = name;
    $("result-until").textContent = "✓ Customers can open this until " + link.last_day_text + ", 11:59 PM";
    const dl = $("result-download");
    dl.href = qrUrl(link.id);
    dl.setAttribute("download", "QR - " + safeFileName(name) + ".png");
    $("result").hidden = false;
    $("layout").classList.add("with-result");
    $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function resetForm() {
    clearFile();
    $("label").value = "";
    $("result").hidden = true;
    $("layout").classList.remove("with-result");
    state.result = null;
    state.choiceTouched = false;
    setChoice({ preset_days: state.status.limits.default_preset_days });
    $("drop").focus();
  }

  // ------------------------------------------------------------------ issued list

  async function loadLinks() {
    try {
      const out = await api("GET", "/api/links");
      state.links = out.links;
      renderLinks();
    } catch (e) {
      /* keep the last good list; the next refresh retries */
    }
  }

  function renderLinks() {
    const list = $("links");
    list.replaceChildren();
    $("links-empty").hidden = state.links.length > 0;
    $("links-count").textContent = state.links.length ? state.links.length + " total" : "";

    for (const link of state.links) {
      const li = el("li", { class: "link-row" });

      const main = el("div", { class: "link-main" });
      main.appendChild(el("div", { class: "link-title", title: link.label || link.filename }, link.label || link.filename));
      const issued = new Date(link.created_at).toLocaleDateString(undefined, {
        weekday: "short", day: "numeric", month: "short",
      });
      main.appendChild(el("div", { class: "link-sub" }, link.filename + " · issued " + issued));
      main.appendChild(el("span", { class: "badge " + link.status.state }, link.status.text));
      li.appendChild(main);

      const actions = el("div", { class: "link-actions" });
      const add = (text, handler, cls) => {
        const b = el("button", { type: "button", class: cls || "" }, text);
        b.addEventListener("click", handler);
        actions.appendChild(b);
      };
      const live = link.status.state === "active" || link.status.state === "expires_today";
      if (live || link.status.state === "expiring") add("Show QR", () => openQrDialog(link));
      if (live) add("Copy link", () => copyLink(link.drive_url));
      if (link.actions.change) add("Change limit", () => openLimitDialog("change", link));
      if (link.actions.reactivate) add("Reactivate", () => openLimitDialog("reactivate", link));
      if (link.actions.end) add("End now", () => confirmEnd(link), "danger");
      li.appendChild(actions);

      list.appendChild(li);
    }
  }

  // ------------------------------------------------------------- dialog: show QR

  function openQrDialog(link) {
    const name = link.label || link.filename;
    $("dlg-qr-title").textContent = name;
    $("dlg-qr-img").src = qrUrl(link.id) + "?v=" + Date.now();
    $("dlg-qr-status").textContent = link.status.text;
    const dl = $("dlg-qr-download");
    dl.href = qrUrl(link.id);
    dl.setAttribute("download", "QR - " + safeFileName(name) + ".png");
    $("dlg-qr-copy-img").onclick = () => copyImage(link.id);
    $("dlg-qr-copy-link").onclick = () => copyLink(link.drive_url);
    $("dlg-qr-print").onclick = () => openPrint(link.id);
    $("dlg-qr").showModal();
  }

  // ------------------------------------------------- dialog: change / reactivate

  function openLimitDialog(mode, link) {
    state.dlg = { mode, link, choice: null };
    const name = link.label || link.filename;
    const isChange = mode === "change";
    $("dlg-limit-title").textContent = isChange ? "Change time limit" : "Reactivate QR code";
    $("dlg-limit-current").textContent = isChange
      ? name + " — currently until " + link.last_day_text + "."
      : name + " — expired " + link.last_day_text + ".";
    $("dlg-limit-note").textContent = isChange
      ? "The same QR code keeps working. Nothing needs to be reprinted or resent."
      : "The file is restored from the Google Drive trash and the same QR code works again.";

    const box = $("dlg-limit-choices");
    box.replaceChildren();
    const values = isChange ? state.status.limits.extend : state.status.limits.presets;
    for (const days of values) {
      const b = el("button", { class: "chip", type: "button", "aria-pressed": "false" },
        (isChange ? "+" : "") + daysWord(days));
      b.dataset.days = String(days);
      b.addEventListener("click", () =>
        setDlgChoice(isChange ? { extend_days: days } : { preset_days: days }));
      box.appendChild(b);
    }
    const until = $("dlg-until");
    configureDateInput(until, state.status.limits);
    until.value = "";
    $("dlg-limit-sentence").textContent = "";
    $("dlg-limit-save").disabled = true;
    $("dlg-limit-save").textContent = isChange ? "Save" : "Reactivate";
    $("dlg-limit").showModal();
  }

  async function setDlgChoice(choice) {
    const d = state.dlg;
    d.choice = choice;
    const days = choice.extend_days !== undefined ? choice.extend_days : choice.preset_days;
    for (const b of $("dlg-limit-choices").children) {
      b.setAttribute("aria-pressed", String(days === Number(b.dataset.days)));
    }
    if (days !== undefined) $("dlg-until").value = "";
    $("dlg-limit-save").disabled = true;
    const url = d.mode === "change"
      ? "/api/links/" + d.link.id + "/limit/preview"
      : "/api/limits/preview";
    const ok = await previewInto($("dlg-limit-sentence"), url, choice);
    $("dlg-limit-save").disabled = !ok;
  }

  async function saveDlg() {
    const d = state.dlg;
    if (!d || !d.choice) return;
    const btn = $("dlg-limit-save");
    btn.disabled = true;
    try {
      const url = "/api/links/" + d.link.id + (d.mode === "change" ? "/limit" : "/reactivate");
      await api("POST", url, d.choice);
      $("dlg-limit").close();
      toast(d.mode === "change" ? "Time limit updated." : "Reactivated — the same QR code works again.");
      loadLinks();
    } catch (e) {
      const s = $("dlg-limit-sentence");
      s.textContent = e.message;
      s.classList.add("bad");
    }
  }

  // ------------------------------------------------------------- dialog: confirm

  function confirmDialog(title, text, okText) {
    return new Promise((resolve) => {
      $("dlg-confirm-title").textContent = title;
      $("dlg-confirm-text").textContent = text;
      $("dlg-confirm-ok").textContent = okText;
      const dlg = $("dlg-confirm");
      const done = (answer) => {
        dlg.close();
        resolve(answer);
      };
      $("dlg-confirm-ok").onclick = () => done(true);
      $("dlg-confirm-cancel").onclick = () => done(false);
      dlg.oncancel = () => resolve(false);
      dlg.showModal();
    });
  }

  async function confirmEnd(link) {
    const yes = await confirmDialog(
      "End this QR code now?",
      "Anyone who scans “" + (link.label || link.filename) + "” will no longer be able to open " +
        "the file. This cannot be undone — you would issue a new QR code instead.",
      "End now"
    );
    if (!yes) return;
    try {
      const out = await api("POST", "/api/links/" + link.id + "/end");
      toast(out.removed_from_drive
        ? "Ended. The file has been removed from sharing."
        : "Ended. Google Drive could not be reached, so the file will be removed as soon as it can.");
      loadLinks();
    } catch (e) {
      toast(e.message);
    }
  }

  // ------------------------------------------------------------------ settings

  function renderDefaultSelect() {
    const sel = $("default-preset");
    sel.replaceChildren();
    for (const days of state.status.limits.presets) {
      const opt = el("option", { value: String(days) }, daysWord(days));
      if (days === state.status.limits.default_preset_days) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  async function saveDefault() {
    const days = Number($("default-preset").value);
    try {
      await api("PUT", "/api/settings", { default_preset_days: days });
      state.status.limits.default_preset_days = days;
      $("settings-saved").textContent = "Saved. New QR codes will last " + daysWord(days) + ".";
      // Apply it to the form now, unless the user has already chosen something else.
      if (!state.choiceTouched && !state.result) setChoice({ preset_days: days });
    } catch (e) {
      $("settings-saved").textContent = e.message;
    }
  }

  async function disconnectDrive() {
    const yes = await confirmDialog(
      "Disconnect Google Drive?",
      "Existing QR codes keep working, but expired ones cannot be removed until you connect again.",
      "Disconnect"
    );
    if (!yes) return;
    try {
      await api("POST", "/api/drive/disconnect");
      toast("Google Drive disconnected.");
    } catch (e) {
      toast(e.message);
    }
    loadStatus();
  }

  // -------------------------------------------------------------------- wiring

  function wire() {
    const drop = $("drop");
    const input = $("file-input");
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        input.click();
      }
    });
    input.addEventListener("change", () => chooseFile(input.files[0]));
    ["dragenter", "dragover"].forEach((t) =>
      drop.addEventListener(t, (e) => {
        e.preventDefault();
        drop.classList.add("over");
      }));
    ["dragleave", "drop"].forEach((t) =>
      drop.addEventListener(t, (e) => {
        e.preventDefault();
        drop.classList.remove("over");
      }));
    drop.addEventListener("drop", (e) => chooseFile(e.dataTransfer.files[0]));
    // Stop a PDF dropped anywhere else from navigating the page away.
    ["dragover", "drop"].forEach((t) => window.addEventListener(t, (e) => e.preventDefault()));

    $("clear-file").addEventListener("click", clearFile);
    $("until").addEventListener("change", (e) => {
      if (!e.target.value) return;
      state.choiceTouched = true;
      setChoice({ until: e.target.value });
    });
    $("create").addEventListener("click", createQr);
    $("connect-drive").addEventListener("click", connectDrive);

    $("result-copy-img").addEventListener("click", () => copyImage(state.result.id));
    $("result-copy-link").addEventListener("click", () => copyLink(state.result.drive_url));
    $("result-print").addEventListener("click", () => openPrint(state.result.id));
    $("new-qr").addEventListener("click", resetForm);

    $("dlg-qr-close").addEventListener("click", () => $("dlg-qr").close());
    $("dlg-limit-cancel").addEventListener("click", () => $("dlg-limit").close());
    $("dlg-limit-save").addEventListener("click", saveDlg);
    $("dlg-until").addEventListener("change", (e) => {
      if (!e.target.value) return;
      setDlgChoice({ until: e.target.value });
    });

    $("open-settings").addEventListener("click", () => {
      $("settings-saved").textContent = "";
      $("dlg-settings").showModal();
    });
    $("dlg-settings-close").addEventListener("click", () => $("dlg-settings").close());
    $("default-preset").addEventListener("change", saveDefault);
    $("disconnect-drive").addEventListener("click", disconnectDrive);
  }

  async function start() {
    wire();
    await loadStatus();
    await loadLinks();
    // Statuses are time-based ("3 days left"), so refresh them periodically.
    setInterval(loadLinks, 60000);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }

  start();
})();
