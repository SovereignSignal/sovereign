/* Settings is a pane, not a drawer.
 *
 * Until 2026-09-21 the seven preferences rendered into the inspector, reachable
 * only by a gear in the Operations toolbar or ⌘,. Home is a different document
 * and offered neither, so the owner landed on the tab that had no route to its
 * own settings and reported not being able to find them. A drawer is also the
 * wrong shape for the things that belong beside them: which archive is open,
 * whether the app is current, and what each producer is permitted to do.
 *
 * The pane mounts into the list column exactly as Hub setup does. It owns no
 * state: preferences live in UserDefaults behind the bridge, and everything
 * else is read from the status the app already has. Saving is explicit, except
 * appearance, which applies immediately because a theme you must confirm reads
 * as broken.
 */
window.SovSettings = (() => {
  let host = null, ctx = {};
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const post = o => window.webkit.messageHandlers.sov.postMessage(o);
  const sect = (title, body, note, acts) => `<div class="set-sect"><h2>${title}</h2>${body}${note ? `<p class="set-note">${note}</p>` : ""}${acts ? `<div class="acts">${acts}</div>` : ""}</div>`;

  /* The app's own currency, in the same words the Home row uses. The revisions
     are evidence and sit under the sentence, never in place of it. */
  function appSection(D) {
    const a = (D && D.machine && D.machine.app) || {}, src = String((D && D.machine && D.machine.template_rev) || "").split(" ")[0];
    if (!a.installed) return sect("This app", `<p class="set-lead">Sovereign is running from a build this machine cannot identify.</p>`, "Install once from this machine's source and it will be able to check itself from then on.");
    const name = `Sovereign ${esc(a.version || "?")} build ${esc(a.build || "?")}`;
    const commit = String(a.source_commit || "").replace("+local", "");
    let lead, action = true, why = "";
    if (!a.source_commit) { lead = `${name} predates update checking, so it cannot tell you whether it is current.`; why = `The bundle records no source revision${src ? `; this machine's source is ${esc(src)}` : ""}.`; }
    else if (!src) { lead = `${name} cannot be checked right now.`; why = "This machine's source revision could not be read, so there is nothing to compare against."; action = false; }
    else if (commit !== src) { lead = `A newer version is ready to install. You are running ${name}.`; why = `Built from source ${esc(commit)}; this machine's source is now ${esc(src)}.`; }
    else { lead = `${name} is the newest build of this machine's source.`; why = `Built from source ${esc(src)}, which is what this machine has.`; action = false; }
    return sect("This app", `<p class="set-lead">${lead}</p>`, why,
      `${action ? `<button class="brass" id="set-update">Update now</button>` : `<button id="set-update">Check again</button>`}<span class="pulls" id="set-update-state" aria-live="polite"></span>`);
  }

  function archiveSection(root) {
    return sect("Archive",
      root ? `<p class="set-lead">Open: <span class="mono">${esc(root)}</span></p>` : `<p class="set-lead">No archive is open.</p>`,
      "Your notes and captures live here. Opening a different archive does not move or copy anything.",
      `<button id="set-change">${root ? "Open a different archive…" : "Open an archive…"}</button>${root ? `<button id="set-reveal">Show in Finder</button>` : ""}`);
  }

  /* What each producer may do, in one table. A lane's permissions are declared
     in its own LANE.md; this reads them back so the owner can see contribute-only
     and read-and-contribute side by side instead of opening seven files. */
  function permissionSection(D) {
    const lanes = (D && D.lanes || []).filter(l => l.lane && l.associated !== false);
    if (!lanes.length) return sect("What each producer may do", `<p class="set-lead">No producer lanes are declared for this archive.</p>`, "Lanes appear here once a producer is onboarded.");
    const level = l => {
      const read = String(l.read || "none").replace(/\s*\(.*\)$/, "");
      return read === "none" || read === "" ? ["Contribute only", "reads nothing from this archive"] : ["Read and contribute", "reads " + esc(l.read_scope || "a declared scope")];
    };
    const rows = lanes.map(l => {
      const [badge, detail] = level(l), findings = l.findings || [];
      // An `info` note is the owner's own answer written down (a retired lane kept as
      // provenance), not something to chase. Only an open question marks the row, or a
      // list of answered ones trains the eye to skip the whole column.
      const worst = findings.some(f => f.level === "bad") ? "bad" : findings.some(f => f.level === "warn") ? "warn" : "";
      const cls = [worst, l.retired ? "retired" : ""].filter(Boolean).join(" ");
      return `<tr${cls ? ` class="${cls}"` : ""}>
        <td>${esc(l.lane)}${l.retired ? "<small>retired</small>" : ""}</td>
        <td><span class="set-badge ${badge === "Contribute only" ? "narrow" : "wide"}">${badge}</span><small>${detail}</small></td>
        <td>${esc(l.write || "—")}</td>
        <td>${esc(l.gear || "—")}</td>
        <td>${findings.length ? findings.map(f => `<span class="set-finding ${esc(f.level)}">${esc(f.text)}</span>`).join("") : "<small>nothing to answer</small>"}</td></tr>`;
    }).join("");
    return sect("What each producer may do",
      `<table class="set-perms"><tr><th>lane</th><th>permission</th><th>writes by</th><th>gear</th><th>drift</th></tr>${rows}</table>`,
      "A lane that reads nothing cannot see your knowledge layer; it may only send. Gear is how far the curator may act on that lane without asking you first.");
  }

  function prefsSection(S, pinned) {
    const pick = (id, label, values, current, render) => sect(`<label for="${id}">${label}</label>`,
      `<select id="${id}">${values.map(v => `<option value="${esc(v)}" ${String(current) === String(v) ? "selected" : ""}>${esc(render(v))}</option>`).join("")}</select>`);
    const where = v => `<label class="radio"><input type="radio" name="set-where" value="${v}" ${S.where === v ? "checked" : ""}> ${v === "dock" ? "Dock" : v === "menubar" ? "Menu bar only" : "Dock and menu bar"}</label>`;
    const login = S.loginState === "on" ? "Registered with macOS." : S.loginState === "off" ? "Not registered." : String(S.loginState || "");
    return sect(`<label for="s-appearance">Appearance</label>`,
             `<select id="s-appearance">${["system", "dark", "light"].map(v => `<option value="${v}" ${(S.appearance || "system") === v ? "selected" : ""}>${v[0].toUpperCase() + v.slice(1)}</option>`).join("")}</select>`,
             "System follows your Mac. Appearance changes save immediately.")
      + sect("Where the app lives", ["dock", "menubar", "both"].map(where).join(""), "The menu bar puts a crown up top; click it for the glance panel. Menu bar only hides the Dock icon.")
      + sect("Closing the window", `<label class="check"><input type="checkbox" id="s-closequits" ${S.closeQuits ? "checked" : ""}> Quit Sovereign when the window closes</label>`,
             "Off, the window closes and Sovereign keeps watching in the background; open it again from the Dock or the crown.")
      + sect("Startup", `<label class="check"><input type="checkbox" id="s-login" ${S.loginItem ? "checked" : ""}> Open at login</label>`, esc(login))
      + pick("s-refresh", "Refresh every", [30, 60, 300, 900], S.refresh, v => v < 60 ? v + " seconds" : (v / 60) + " minute" + (v > 60 ? "s" : ""))
      + pick("s-view", "Open on", ["glance", "hosts", "archive", "lanes", "tools", "jobs", "backups"], S.defaultView, v => v === "jobs" ? "Hub" : v[0].toUpperCase() + v.slice(1))
      + sect("Detail panel", `<label class="check"><input type="checkbox" id="s-pin" ${pinned ? "checked" : ""}> Keep it open beside the list</label>`);
  }

  function render() {
    if (!host || !host.isConnected) return;
    const { S = {}, D = null, root = null, pinned = false } = ctx;
    host.className = "";
    host.innerHTML = `<div class="set-pane">
      <div class="set-head"><h1>Settings</h1><p>This app, this archive, and what each producer is allowed to do. Preferences are saved on this Mac.</p></div>
      ${archiveSection(root)}
      ${appSection(D)}
      ${permissionSection(D)}
      ${prefsSection(S, pinned)}
      ${S.error ? `<div class="note">${esc(S.error)}</div>` : ""}
      <div class="acts set-save"><button class="brass" id="s-save">Save settings</button><span class="pulls" id="s-state" aria-live="polite"></span></div>
    </div>`;
  }

  return {
    mount(el, next) { host = el; ctx = Object.assign({}, ctx, next); render(); },
    /* Re-render in place when the bridge answers, so a save or an update result
       lands without the owner losing their scroll position in a long pane. */
    refresh(next) { if (next) ctx = Object.assign({}, ctx, next); render(); },
    note(id, text) { const n = host && host.querySelector("#" + id); if (n) n.textContent = text; },
    get mounted() { return !!(host && host.isConnected && host.querySelector(".set-pane")); }
  };
})();
