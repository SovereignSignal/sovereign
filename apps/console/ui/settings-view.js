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

  /* The app's own currency. Check for updates asks the signed GitHub release and is
     always offered: nothing is contacted until it is clicked. Update from source appears
     only when this device's checkout holds a newer build, in the same words the Today
     row uses; otherwise that comparison sits behind Details, with its evidence. */
  function appSection(D) {
    if (unread(D)) return sect("Version", say(unread(D)));
    const m = (D && D.machine) || {}, a = m.app || {}, src = String(m.template_rev || "").split(" ")[0];
    if (!a.installed) return sect("Version", `<p class="set-lead">Sovereign is running from a build this device cannot identify.</p>`, "Install once from this device's source and it will be able to check itself from then on.");
    const name = `Sovereign ${esc(a.version || "?")} build ${esc(a.build || "?")}`;
    const commit = String(a.source_commit || "").replace("+local", "");
    let lead, action = true, why = "";
    if (!a.source_commit) { lead = `${name} predates update checking, so it cannot tell you whether it is current.`; why = `The bundle records no source revision${src ? `; this device's source is ${esc(src)}` : ""}.`; }
    else if (!src) { lead = `${name} cannot be checked right now.`; why = "This device's source revision could not be read, so there is nothing to compare against."; action = false; }
    else if (commit !== src && a.behind === false) { lead = `${name} was built from newer or different source than this device has, so there is nothing newer to install.`; why = `Built from source ${esc(commit)}, which this device's source ${esc(src)} does not contain.`; action = false; }
    else if (commit !== src) { lead = `A newer version is ready to install. You are running ${name}.`; why = `Built from source ${esc(commit)}; this device's source is now ${esc(src)}.`; }
    else { lead = `${name} is the newest build of this device's source.`; why = `Built from source ${esc(src)}, which is what this device has.`; action = false; }
    const fromSource = action && !!m.template;
    const body = fromSource
      ? `<p class="set-lead">${lead}</p>${more("Details", `<p class="set-note">${why}</p>`)}`
      : `<p class="set-lead">You are running ${name}.</p>${more("Details", `<p class="set-note">${lead}</p><p class="set-note">${why}</p>`)}`;
    return sect("Version", `${body}<span class="pulls" id="set-update-state" aria-live="polite"></span>`, "",
      `<button class="brass" id="set-update">Check for updates</button>${fromSource ? `<button id="set-update-source">Update from source</button>` : ""}`);
  }

  function archiveSection(root) {
    return sect("Archive",
      root ? `<p class="set-lead"><span class="mono">${esc(root)}</span></p>` : `<p class="set-lead">No archive is open.</p>`, "",
      `<button id="set-change">${root ? "Change…" : "Open an archive…"}</button>${root ? `<button id="set-reveal">Show in Finder</button>` : ""}`);
  }

  /* The curator for an archive with no hub: the owner's chosen provider under their
     own key, every two
     hours, in ask-first until the owner grants background landing. A Mac that runs a hub
     curates from its own jobs, so the section says that instead of a second curator. */
  /* Making a provider key is where a newcomer stalls, so each provider's own pages are a
     click away, in the browser. Checked against each provider's documentation on
     2026-10-20. Where a provider documents no spend limit (xAI) or no public sign-up
     (Muse), the guide says so instead of guessing. */
  const KEY_GUIDES = {
    anthropic: { steps: ["Sign in to the Claude Console, or create an account, and add credits under Billing.",
                         "On API keys, choose Create key, name it Sovereign, and copy it. It is shown only once.",
                         "Optional: on Billing, under Spend limits, choose Set limit to cap what a month can cost."],
                 links: [["https://platform.claude.com/settings/keys", "API keys"], ["https://platform.claude.com/settings/billing", "Billing"]] },
    openai: { steps: ["Sign in to the OpenAI API platform, or create an account, and add credits under Billing.",
                      "Under API keys, choose Create new secret key, name it Sovereign, and copy it. It is shown only once.",
                      "Optional: on Limits, under Spend, choose Edit spend limit and turn on Enforce a hard limit."],
              links: [["https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key", "Finding your key"], ["https://platform.openai.com/settings/organization/limits", "Limits"]] },
    gemini: { steps: ["Sign in to Google AI Studio with your Google account.",
                      "On API keys, choose Create API key and copy it. Keys made there work with the Gemini API, which is all Sovereign uses.",
                      "Optional: on Spend, under Monthly spend cap, choose Edit spend cap. Google notes spend can run slightly past the cap."],
              links: [["https://aistudio.google.com/apikey", "API keys"], ["https://aistudio.google.com/spend", "Spend"]] },
    grok: { steps: ["Sign in to the xAI Console, or create an account, and load it with credits.",
                    "On API keys, create a key, name it Sovereign, and copy it.",
                    "xAI's documentation describes no spend limit, so the credits you load are what the curator can draw on."],
            links: [["https://console.x.ai/team/default/api-keys", "API keys"]] },
    muse: { steps: ["Muse has no public sign-up page yet. Ask whoever runs your Muse endpoint for a key and its address."], links: [] },
  };
  function keyGuide(id, name, open) {
    const g = KEY_GUIDES[id];
    if (!g) return "";
    const steps = `<ol class="set-steps">${g.steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol>`;
    const links = g.links.length ? `<div class="set-inline set-links">${g.links.map(([url, label]) => `<button data-act="openurl" data-url="${esc(url)}">${esc(label)} ↗</button>`).join("")}</div>` : "";
    return more(`Get your ${esc(name)} key`, steps + links
      + `<p class="set-note">Pages open in your browser. Sovereign only needs the key, never your password, and keeps it in this Mac's Keychain.</p>`, open);
  }

  function curatorSection(C) {
    if (!C) return sect("Curator", say("Checking…"));
    if (C.hub) return sect("Curator", say("Your hub curates this archive."));
    if (C.error) return sect("Curator", say(esc(C.error)));
    const on = C.installed && C.loaded, pending = C.pending || 0, T = C.trust_record || {};
    const trustState = T.state || C.trust || "ask-first", trusted = trustState === "act-and-report";
    const incomplete = trustState === "incomplete" || T.repair_needed === true;
    const P = (Array.isArray(C.providers) ? C.providers : []).find(p => p.id === C.provider)
      || { name: "Anthropic", hint: "sk-ant-…" };
    const lead = !C.key_saved ? `Add your ${P.name} API key to turn on the curator.`
      : on ? `${P.name} curates this archive every two hours. ${pending ? pending + " waiting in Review." : "Nothing waiting."}`
      : "The curator is off.";
    const clean = Number.isFinite(T.clean_streak) ? T.clean_streak : 0,
          threshold = Number.isFinite(T.threshold) && T.threshold > 0 ? T.threshold : 10;
    let trustSay = "";
    if (C.key_saved && trusted) {
      const landed = T.auto_landed_30d || 0, reverted = T.auto_reverted_30d || 0;
      trustSay = `<p class="set-note"><strong>Background landing is on.</strong> Routine concepts and syntheses at high and medium confidence can land without waiting, at most 12 per pass. ${landed} landed on their own in the last 30 days${reverted ? `; ${reverted} later reverted` : ""}. Flagged items, entities, collisions, and destructive changes still ask first.</p>`;
    } else if (C.key_saved && incomplete) {
      trustSay = `<p class="set-note"><strong>Trust needs repair.</strong> The background-landing switch and its grants disagree, so Sovereign is treating routine cards as ask-first until they are reconciled.</p>`;
    } else if (C.key_saved && T.eligible) {
      trustSay = `<p class="set-note"><strong>The curator has earned more room.</strong> Your last ${clean} routine concept and synthesis decisions were approvals, with no routine rejection or retirement in between. You can let that class of card land in the background and report back.</p>`;
    } else if (C.key_saved) {
      trustSay = `<p class="set-note">Background landing is off. ${clean} of ${threshold} clean routine decisions toward Sovereign offering it. Routine here means high- or medium-confidence concepts and syntheses.</p>`;
    }
    const recent = Array.isArray(T.recent_auto_landed) ? T.recent_auto_landed.slice(0, 5) : [];
    const landedList = recent.length ? more("Recently landed on their own",
      recent.map(r => `<p class="set-note set-landed"><span><span class="mono">${esc(r.slug || "")}</span> · ${esc(r.type || "card")} · ${esc(r.confidence || "")}${r.ts ? ` · ${esc(String(r.ts).slice(0, 10))}` : ""}${r.reverted ? " · reverted" : ""}</span>${r.reverted ? "" : `<button data-cur-retire="${esc(r.slug || "")}">Retire…</button>`}</p>`).join("")
      + `<p class="set-note">Retiring moves the card out of trusted knowledge into the curator's rejected archive. It is never deleted.</p>`) : "";
    const picker = Array.isArray(C.providers) && C.providers.length
      ? `<div class="set-inline">${C.providers.map(p => `<button data-cur-provider="${esc(p.id)}"${p.id === C.provider ? ` class="brass"` : ""}>${esc(p.name)}</button>`).join("")}</div>` : "";
    const key = `<div class="set-inline"><input type="password" id="set-cur-key" autocomplete="off" spellcheck="false" placeholder="${C.key_saved ? "Replace key…" : esc(P.hint || "API key…")}" aria-label="${esc(P.name)} API key"><button id="set-cur-save">Save key</button></div>`;
    const trustAct = !C.key_saved ? ""
      : trusted ? `<button id="set-cur-untrust">Ask first again</button>`
      : incomplete ? `<button class="brass" id="set-cur-trust">Repair trust</button>`
      : T.eligible ? `<button class="brass" id="set-cur-trust">Let routine cards land</button>` : "";
    const acts = C.key_saved ? (on ? `<button class="brass" id="set-cur-run">Curate now</button>${trustAct}<button id="set-cur-off">Turn off</button>`
                                   : `<button class="brass" id="set-cur-on">Turn on</button>${trustAct}`) : "";
    const note = trusted
      ? `Your key stays in this Mac's Keychain. Each pass sends new material to ${P.name} under your account. Switching provider returns to ask-first. Auto-rejection stays off.`
      : `Your key stays in this Mac's Keychain. Each pass sends new material to ${P.name} under your account. Cards wait for you in Review until you grant background landing.`;
    const guide = keyGuide(C.provider || "anthropic", P.name, !C.key_saved);
    return sect("Curator", say(lead) + picker + key + guide + trustSay + landedList + `<span class="pulls" id="set-cur-state" aria-live="polite"></span>`, note, acts);
  }

  /* Session capture (`sov ingest sessions status --json`): quiet Claude Code sessions,
     distilled on this archive's own curator provider into the tool's lane as untrusted
     captures. Off until the owner turns it on, and Turn on is offered only once a Preview
     (the dry plan, no model call) has rendered here, so nobody switches on blind. A Mac
     that sends its work to a hub has no model of its own here and says so. */
  function sessionSection(X, plan, previewed) {
    const T = "Session capture";
    if (!X) return sect(T, say("Checking…"));
    if (X.error) return sect(T, say(esc(X.error)));
    const off = `<button id="set-ses-off">Turn off</button>`;
    // A config switched on before this Mac's role changed keeps its Turn off here too.
    if (X.mode === "client") return sect(T, say("Session capture is off on this Mac.") + (X.reason ? `<p class="set-note">${esc(X.reason)}</p>` : ""), "", X.enabled ? off : "");
    if (!X.available) {
      const r = String(X.reason || "no model can read a session here").trim();
      const line = /^[a-z]/.test(r) ? `Session capture ${r}${/[.!?]$/.test(r) ? "" : "."}` : r;
      // Capture already on with its model gone keeps a way to switch it off; never on.
      return sect(T, say(esc(line)), "", X.enabled ? off : "");
    }
    const d = X.distiller || {}, b = X.budget || {}, w = X.week || {};
    const nextUp = (Array.isArray(X.next) ? X.next : []).map(n => `<p class="set-note">${esc(n.label)}: next</p>`).join("");
    const projects = (Array.isArray(X.projects) ? X.projects : []).filter(p => p.kind !== "archive");
    const n = k => Number.isFinite(k) ? k : 0;
    const rows = projects.map(p => `<label class="check" title="${esc(p.path)}"><input type="checkbox" data-ses-path="${esc(p.path)}"${p.on ? " checked" : ""}> ${esc(p.label || p.path)} <small>${n(p.sessions)} session${n(p.sessions) === 1 ? "" : "s"}</small></label>`).join("")
      + `<label class="check"><input type="checkbox" disabled> Inside an archive: never</label>`;
    const week = X.enabled ? `<p class="set-note">This week: distilled ${n(w.distilled)}, captures ${n(w.captures)}, skipped ${n(w.skipped)}, waiting ${n(w.waiting)}, failed ${n(w.failed)}, refused ${n(w.refused)}.</p>`
      + (X.waiting && X.waiting.reason ? `<p class="set-note set-ses-waiting">Waiting: ${esc(X.waiting.reason)} since ${esc(X.waiting.since || "")}.</p>` : "") : "";
    const body = `<p class="set-lead">Claude Code: distill quiet sessions into its lane <span class="set-ses-switch${X.enabled ? " on" : ""}">${X.enabled ? "On" : "Off"}</span></p>`
      + nextUp
      + `<p class="set-note">Uses your curator's provider: ${esc(d.name || d.provider || "none")}</p>`
      + week
      + `<div class="set-ses-projects">${rows}</div>`
      + (projects.length ? "" : `<p class="set-note">No Claude Code sessions in the last 30 days.</p>`)
      + `<p class="set-note">Up to ${n(b.calls_per_tick)} sessions a tick and ${n(b.calls_per_day)} a day, oldest first.</p>`
      + (plan ? `<pre class="set-prompt set-ses-plan">${esc(plan)}</pre>` : "")
      + `<span class="pulls" id="set-ses-state" aria-live="polite"></span>`;
    const acts = `<button id="set-ses-preview">Preview</button>`
      + (X.enabled ? off : previewed && plan ? `<button class="brass" id="set-ses-on">Turn on</button>` : "");
    const note = X.enabled ? "Transcripts stay on this Mac. A cleaned excerpt of each quiet session that passes the pre-filter goes to the distiller, and what it keeps lands untrusted in the lane for the curator and you to judge."
      : "Preview shows what the next tick would read, with no model call. Turn on appears after it.";
    return sect(T, body, note, acts);
  }

  /* What ChatGPT already remembers, brought in without a terminal. The prompt is the one
     `sov import chatgpt --prompt` prints, so the app and the command line never ask
     ChatGPT different things. A preview always comes before Import, and Import only
     writes untrusted captures: the curator and the owner still decide what becomes a card.
     The pane re-renders on every status refresh, so the pasted answer lives here, not in
     the textarea. */
  let importText = "";
  function importSection(I) {
    I = I || {};
    const prompt = I.prompt ? `<pre class="set-prompt" id="set-imp-prompt">${esc(I.prompt)}</pre>`
      : `<p class="set-note">${esc(I.error || "Loading the prompt…")}</p>`;
    const body = say("Bring in what ChatGPT remembers about you.")
      + `<p class="set-note">1. Copy this prompt into a new ChatGPT chat, with memory on.</p>` + prompt
      + `<p class="set-note">2. Paste ChatGPT's whole answer below, then preview what will come in.</p>`
      + `<textarea id="set-imp-text" rows="7" spellcheck="false" aria-label="ChatGPT's answer" placeholder="## A short title&#10;Two to five sentences ChatGPT remembers.">${esc(importText)}</textarea>`
      + (I.plan ? `<pre class="set-prompt set-imp-plan">${esc(I.plan)}</pre>` : "")
      + `<span class="pulls" id="set-imp-state" aria-live="polite"></span>`;
    const acts = (I.prompt ? `<button data-act="copy" data-text="${esc(I.prompt)}">Copy prompt</button>` : "")
      + `<button id="set-imp-preview">Preview</button>`
      + (I.ready ? `<button class="brass" id="set-imp-apply">Import</button>` : "");
    return sect("Import", body,
      "Each memory lands untrusted as its own capture. The curator judges each one, and nothing becomes a card until you approve it.", acts);
  }
  document.addEventListener("input", e => {
    if (e.target && e.target.id === "set-imp-text") importText = e.target.value;
  });

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
    const { S = {}, D = null, root = null, pinned = false, curator = null, imports = null,
            sessions = null, sessionsPlan = "", sessionsPreviewed = false } = ctx;
    host.className = "";
    host.innerHTML = `<div class="set-pane">
      ${archiveSection(root)}
      ${root ? curatorSection(curator) : ""}
      ${root ? sessionSection(sessions, sessionsPlan, sessionsPreviewed) : ""}
      ${root ? importSection(imports) : ""}
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
    importText(next) { if (next !== undefined) importText = next; return importText; },
    get mounted() { return !!(host && host.isConnected && host.querySelector(".set-pane")); }
  };
})();
