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
 *
 * Each setting is one row: its name, its value, its control. Evidence and the
 * permissions table open on request, so the pane reads at a glance.
 */
window.SovSettings = (() => {
  let host = null, ctx = {};
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const post = o => window.webkit.messageHandlers.sov.postMessage(o);
  const sect = (title, body, note, acts) => `<div class="set-sect"><h2>${title}</h2><div class="set-body">${body}${note ? `<p class="set-note">${note}</p>` : ""}</div>${acts ? `<div class="acts">${acts}</div>` : ""}</div>`;
  const more = (summary, body, open) => `<details class="set-more"${open ? " open" : ""}><summary>${summary}</summary>${body}</details>`;

  /* Before the first status arrives, or when it could not be read, there is no
     build, job or lane to describe: say so instead of an empty answer. */
  const unread = D => !D || D.error || (D._status && !D.machine) ? (D && D.error ? "Status unavailable" : "Checking…") : "";
  const say = text => `<p class="set-lead">${text}</p>`;

  /* The app's own currency, in the same words the Today row uses. The revisions
     are evidence and sit behind the sentence, never in place of it. */
  function appSection(D) {
    if (unread(D)) return sect("Version", say(unread(D)));
    const a = (D && D.machine && D.machine.app) || {}, src = String((D && D.machine && D.machine.template_rev) || "").split(" ")[0];
    if (!a.installed) return sect("Version", `<p class="set-lead">Sovereign is running from a build this device cannot identify.</p>`, "Install once from this device's source and it will be able to check itself from then on.");
    const name = `Sovereign ${esc(a.version || "?")} build ${esc(a.build || "?")}`;
    const commit = String(a.source_commit || "").replace("+local", "");
    let lead, action = true, why = "";
    if (!a.source_commit) { lead = `${name} predates update checking, so it cannot tell you whether it is current.`; why = `The bundle records no source revision${src ? `; this device's source is ${esc(src)}` : ""}.`; }
    else if (!src) { lead = `${name} cannot be checked right now.`; why = "This device's source revision could not be read, so there is nothing to compare against."; action = false; }
    else if (commit !== src && a.behind === false) { lead = `${name} was built from newer or different source than this device has, so there is nothing newer to install.`; why = `Built from source ${esc(commit)}, which this device's source ${esc(src)} does not contain.`; action = false; }
    else if (commit !== src) { lead = `A newer version is ready to install. You are running ${name}.`; why = `Built from source ${esc(commit)}; this device's source is now ${esc(src)}.`; }
    else { lead = `${name} is the newest build of this device's source.`; why = `Built from source ${esc(src)}, which is what this device has.`; action = false; }
    return sect("Version", `<p class="set-lead">${lead}</p>${more("Details", `<p class="set-note">${why}</p>`)}<span class="pulls" id="set-update-state" aria-live="polite"></span>`, "",
      action ? `<button class="brass" id="set-update">Update now</button>` : `<button id="set-update">Check again</button>`);
  }

  function archiveSection(root) {
    return sect("Archive",
      root ? `<p class="set-lead"><span class="mono">${esc(root)}</span></p>` : `<p class="set-lead">No archive is open.</p>`, "",
      `<button id="set-change">${root ? "Change…" : "Open an archive…"}</button>${root ? `<button id="set-reveal">Show in Finder</button>` : ""}`);
  }

  /* A job is what an operating system schedules; a lane runs inside one. The Jobs
     header counts with this too, so the two places never disagree. */
  function jobCount(D) {
    const local = (D && D.jobs) || [], lanes = local.filter(j => j.kick).length;
    return { jobs: Object.keys((D && D.hub && D.hub.jobs) || {}).length + local.length - lanes, lanes };
  }

  /* The scheduled work behind the archive. It is engine-room detail, so it has a
     door here and no place in the navigation. */
  function jobsSection(D) {
    const n = jobCount(D).jobs;
    return sect("Jobs", say(unread(D) || (n ? n + " scheduled" : "None reported")), "",
      `<button data-goto-view="jobs">View</button><button data-goto-view="setup">Hub setup…</button>`);
  }

  /* What each producer may do, in one table. A lane's permissions are declared
     in its own LANE.md; this reads them back so the owner can see contribute-only
     and read-and-contribute side by side instead of opening seven files. */
  function permissionSection(D) {
    if (unread(D)) return sect("Permissions", say(unread(D)));
    const lanes = (D && D.lanes || []).filter(l => l.lane && l.associated !== false);
    if (!lanes.length) return sect("Permissions", say("No producer lanes are declared for this archive."));
    // `read` carries its mechanism in parentheses and `read_scope` is sometimes the
    // bare boolean `true` rather than a scope, which rendered as "reads true". Say
    // what is actually known: the scope when there is one, else the mechanism.
    const level = l => {
      const full = String(l.read || "none").trim();
      // Classify on the bare mechanism; show the whole thing, because the
      // parenthetical is where "when does it read" actually lives.
      if (!full || full.replace(/\s*\(.*\)$/, "").trim().replace(/^none$/, "") === "") return ["Contribute only", "reads nothing from this archive"];
      const scope = typeof l.read_scope === "string" && l.read_scope.trim() ? l.read_scope.trim() : "";
      return ["Read and contribute", "reads via " + esc(full) + (scope ? ", scoped to " + esc(scope) : "")];
    };
    const row = l => {
      const [badge, detail] = level(l), findings = l.findings || [];
      // An `info` note is the owner's own answer written down (a retired lane kept as
      // provenance), not something to chase. Only an open question marks the row, or a
      // list of answered ones trains the eye to skip the whole column.
      const worst = findings.some(f => f.level === "bad") ? "bad" : findings.some(f => f.level === "warn") ? "warn" : "";
      const cls = [worst, l.retired ? "retired" : ""].filter(Boolean).join(" ");
      return `<tr${cls ? ` class="${cls}"` : ""}>
        <td>${esc(l.lane)}${l.retired ? "<small>retired</small>" : ""}${l.producer ? `<small>${esc(l.producer)}</small>` : ""}</td>
        <td class="set-where">${esc(l.host || "—")}</td>
        <td><span class="set-badge ${badge === "Contribute only" ? "narrow" : "wide"}">${badge}</span><small>${detail}</small></td>
        <td>${esc(l.write || "—")}</td>
        <td>${esc(l.gear || "—")}</td>
        <td>${findings.length ? findings.map(f => `<span class="set-finding ${esc(f.level)}">${esc(f.text)}</span>`).join("") : "<small>nothing to answer</small>"}</td></tr>`;
    };
    // Grouped by host, because "what runs where" is the question the flat list could
    // not answer: the machine is the shape of the table, not a column to read down.
    const byHost = new Map();
    for (const l of lanes) {
      const where = l.host || "unplaced";
      if (!byHost.has(where)) byHost.set(where, []);
      byHost.get(where).push(l);
    }
    const groups = [...byHost.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    const rows = groups.map(([where, ls]) =>
      `<tr class="set-host"><th colspan="6">${esc(where)}<small>${ls.length} lane${ls.length === 1 ? "" : "s"}</small></th></tr>`
      + ls.map(row).join("")).join("");
    // An open question opens the table; a settled one stays behind its count.
    const open = lanes.filter(l => (l.findings || []).some(f => f.level === "warn" || f.level === "bad")).length;
    return sect("Permissions", more(`${lanes.length} source${lanes.length === 1 ? "" : "s"}${open ? ` · ${open} to settle` : ""}`,
      `<table class="set-perms"><tr><th>lane</th><th>where</th><th>permission</th><th>writes by</th><th>gear</th><th>drift</th></tr>${rows}</table>
       <p class="set-note">A lane that reads nothing cannot see your knowledge layer; it may only send. Gear is how far the curator may act on that lane without asking you first.</p>`, open > 0));
  }

  function prefsSection(S, pinned) {
    const pick = (id, label, values, current, render) => sect(`<label for="${id}">${label}</label>`,
      `<select id="${id}">${values.map(v => `<option value="${esc(v)}" ${String(current) === String(v) ? "selected" : ""}>${esc(render(v))}</option>`).join("")}</select>`);
    const where = v => `<label class="radio"><input type="radio" name="set-where" value="${v}" ${S.where === v ? "checked" : ""}> ${v === "dock" ? "Dock" : v === "menubar" ? "Menu bar" : "Both"}</label>`;
    const login = S.loginState === "on" ? "Registered with macOS." : S.loginState === "off" ? "Not registered." : String(S.loginState || "");
    return sect(`<label for="s-appearance">Appearance</label>`,
             `<select id="s-appearance">${["system", "dark", "light"].map(v => `<option value="${v}" ${(S.appearance || "system") === v ? "selected" : ""}>${v[0].toUpperCase() + v.slice(1)}</option>`).join("")}</select>`)
      + sect("Shows in", `<div class="set-inline">${["dock", "menubar", "both"].map(where).join("")}</div>`)
      // Native quits on close only from the Dock: a menu bar crown keeps Sovereign running.
      + sect("On close", `<label class="check"><input type="checkbox" id="s-closequits" ${S.closeQuits ? "checked" : ""}${S.where === "dock" ? "" : " disabled"}> Quit Sovereign</label><p class="set-note" id="s-closequits-note"${S.where === "dock" ? " hidden" : ""}>Dock only</p>`)
      + sect("At login", `<label class="check"><input type="checkbox" id="s-login" ${S.loginItem ? "checked" : ""}> Open Sovereign</label>`, esc(login))
      + pick("s-refresh", "Refresh every", [30, 60, 300, 900], S.refresh, v => v < 60 ? v + " seconds" : (v / 60) + " minute" + (v > 60 ? "s" : ""))
      + sect("Detail panel", `<label class="check"><input type="checkbox" id="s-pin" ${pinned ? "checked" : ""}> Keep it open beside the list in a wide window</label>`);
  }

  function render() {
    if (!host || !host.isConnected) return;
    const { S = {}, D = null, root = null, pinned = false } = ctx;
    host.className = "";
    host.innerHTML = `<div class="set-pane">
      ${archiveSection(root)}
      ${appSection(D)}
      ${prefsSection(S, pinned)}
      ${S.error ? `<div class="note">${esc(S.error)}</div>` : ""}
      <div class="acts set-save"><button class="brass" id="s-save">Save</button><span class="pulls" id="s-state" aria-live="polite"></span></div>
      ${jobsSection(D)}
      ${permissionSection(D)}
    </div>`;
  }

  // Choosing where it shows applies to On close before Save, so the box never lies.
  document.addEventListener("change", e => {
    if (e.target.name !== "set-where") return;
    const box = document.getElementById("s-closequits"), note = document.getElementById("s-closequits-note"), dock = e.target.value === "dock";
    if (box) box.disabled = !dock;
    if (note) note.hidden = dock;
  });

  return {
    jobCount,
    mount(el, next) { host = el; ctx = Object.assign({}, ctx, next); render(); },
    /* Re-render in place when the bridge answers, so a save or an update result
       lands without the owner losing their scroll position in a long pane. */
    refresh(next) { if (next) ctx = Object.assign({}, ctx, next); render(); },
    note(id, text) { const n = host && host.querySelector("#" + id); if (n) n.textContent = text; },
    get mounted() { return !!(host && host.isConnected && host.querySelector(".set-pane")); }
  };
})();
