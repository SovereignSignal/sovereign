'use strict';
// Shared assessment for Home, Review, Operations and menu-bar Glance.
window.SovStatus = (() => {
  const age = (h) => h == null ? "–" : h < 1 ? Math.max(1, Math.round(h * 60)) + "m" : h < 48 ? (Math.round(h * 10) / 10) + "h" : Math.round(h / 24) + "d";

  const num = (n) => n == null ? "?" : Number(n).toLocaleString();

  const runAge = (s, at = Date.now()) => { const m = /Last run: (\S+)/.exec(s || ""); if (!m) return null; const t = Date.parse(m[1]); return isNaN(t) ? null : (at - t) / 36e5; };

  const intervalOf = (t) => { if (t && t.cadence_s) return +t.cadence_s;
    const m = /every (\d+)s/.exec(((t && t.plist) || {}).schedule || ""); return m ? +m[1] : 900; };
  function isoWeekKey(d) {
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day);
    const y = t.getUTCFullYear(), w = Math.ceil((((t - Date.UTC(y, 0, 1)) / 864e5) + 1) / 7);
    return y + "-W" + String(w).padStart(2, "0");
  }
  const HUB_CADENCE_H = { "archivist-nightly": 24, "archivist-weekly": 168, "archivist-weekly-landed": 168, "daily-health-check": 24,
    "vault-autocommit": 24, "fleet-watch": 1, "fleet-watch-drill": 168, "proxmox-monitor": 24, "pi-cluster-monitor": 24 };
  // Cards carry age_d, whole days since created on the status service's calendar.
  const landedToday = (D) => ((D.archive || {}).cards || []).filter(c => c.age_d != null && c.age_d < 1).length;
  const shortLabel = (l) => String(l).replace(/^com\.[a-z]+\.(connector|cron)\./, "");
  function jobProgress(job, status = {}) {
    const p = job.progress, now = Date.now()/1000;
    if (!p || p.phase === 'completed') return null;
    if (status._status?.stale || !Number.isFinite(p.checked_at) || now-p.checked_at > 300 || p.checked_at > now+5)
      return {label:'Refresh progress',summary:'Progress observation is out of date',tone:'warn'};
    if (!p.active) return {label:'Progress ended',summary:'Recorded worker is no longer running; check the completion receipt',tone:'warn'};
    const elapsed = Number.isFinite(p.no_progress_s) ? age(p.no_progress_s/3600) : '?';
    return {label:p.phase === 'waiting_model' ? 'Waiting' : 'Running',
      summary:String(p.summary || 'Working')+'; last progress '+elapsed+' ago',tone:'warn'};
  }
  function hubJob(job, status = {}) {
    const health = job.health || {}, now = Date.now()/1000;
    let state = job.exit === 0 ? 'healthy' : job.exit == null ? 'unknown' : 'needs_attention';
    let action=health.action;
    let summary = health.summary || (state === 'healthy' ? 'Last run succeeded' : state === 'unknown' ? 'No completed run recorded' : 'Last run failed');
    if (state === 'needs_attention' && health.state === 'awaiting_verification') {
      if (!Number.isFinite(health.verification_deadline) || now > health.verification_deadline) {summary = 'Backup verification is overdue';action='Refresh the job record and check the scheduler; run the backup again if no newer success is recorded.';}
      else if (status._status?.stale || !Number.isFinite(health.checked_at) || now-health.checked_at > 300) {summary = 'Refresh to check backup recovery';action='Refresh status to verify the current blocker and hub connection before retrying.';}
      else state = 'awaiting_verification';
    }
    // A job that stood down on purpose (runner.PAUSED_EXIT) reports a condition, not a
    // failure: the owner clears it by deciding, and nothing about the job needs repair.
    if (state === 'needs_attention' && health.state === 'paused') state = 'paused';
    const progress = jobProgress(job,status);
    return {...health, state, summary:progress ? progress.summary+'; '+summary : summary, action,
      tone:state === 'needs_attention' ? 'down' : progress ? progress.tone : state === 'healthy' ? 'live' : state === 'paused' ? 'warn' : '',
      label:progress ? progress.label : state === 'awaiting_verification' ? 'Awaiting verification' : state === 'paused' ? 'Paused' : state === 'needs_attention' ? 'Needs attention' : state === 'healthy' ? 'Succeeded' : 'Unknown'};
  }
  // How complete is the archive, from numbers that are already true rather than a score.
  // One headline figure only: the share of eligible material the curator has actually
  // read. Producers and the gate sit beside it because a high share means little if the
  // things that feed it stopped, and a decision waiting on the owner is not the same
  // kind of incomplete as material not yet read.
  function completeness(D) {
    const st = (D && D.hub && D.hub.status) || {}, cov = st.coverage || {};
    const total = Number(cov.processable) || 0, judged = Number(cov.judged_ever) || 0;
    const lanes = (D && D.lanes || []).filter(l => !l.retired);
    // "Delivering" is the lane's own declared cadence, not a fixed clock: a lane that
    // collects weekly is not behind at six days.
    const live = lanes.filter(l => l.vault_age_h != null && l.vault_age_h <= 48).length;
    const gate = Number((D && D.hub && D.hub.pending)) || 0;
    const pct = total > 0 ? Math.round((judged / total) * 100) : null;
    const parts = [];
    if (pct != null) parts.push(pct + "% read");
    if (lanes.length) parts.push(live + " of " + lanes.length + " producers delivering");
    parts.push(gate ? (gate + " waiting on you") : "nothing waiting on you");
    return {
      read: { judged, total, pct },
      waiting: Number(cov.unjudged_in_window) || 0,
      out_of_reach: Number(cov.stranded_pre_watermark) || 0,
      producers: { delivering: live, total: lanes.length },
      gate,
      headline: parts.join(" \u00b7 "),
      // Said plainly, because a percentage on its own invites the wrong conclusion.
      detail: total > 0
        ? judged.toLocaleString() + " of " + total.toLocaleString() + " eligible items have been read by the curator."
        : "The curator has not reported what it can see yet."
    };
  }

  function backupState(h) {
    if(h.backup_required===false)return {state:'idle',label:'not required',text:'Backup alerts excluded on this Mac',issue:null};
    if(!h.reachable)return {state:'',label:'unknown',text:'Proxmox could not be reached',issue:null};
    const hasBackup=Number.isFinite(h.last_dump_age_h),incomplete=h.inventory_complete!==true;
    if(incomplete)return {state:'warn',label:'unknown',text:hasBackup?'Backup found; storage checks incomplete':'Backup storage could not be fully checked',issue:'backup-unknown'};
    if(typeof h.scheduled!=='boolean')return {state:'warn',label:'unknown',text:hasBackup?'Backup found; schedule coverage unknown':'Backup schedule coverage unknown',issue:'backup-unknown'};
    if(!hasBackup)return {state:'down',label:h.scheduled===false?'not scheduled':'unprotected',text:h.scheduled===false?'No enabled backup job includes this VM':'No completed backup found in Proxmox storage',issue:'no-backup'};
    if(h.scheduled===false)return {state:'warn',label:'not scheduled',text:'Backup exists; no enabled job includes this VM',issue:'backup-unscheduled'};
    if(h.last_dump_age_h>=48)return {state:'warn',label:'stale',text:'Latest backup is over 48 hours old',issue:'backup-stale'};
    return {state:'live',label:'backed up',text:'Backup recorded'+(h.last_backup?.storage?' on '+h.last_backup.storage:''),issue:null};
  }
  function backupScope(value) {
    const config=value?.backup_scope;
    if(!config?.available||config.scope!==value.machine?.vault)return value;
    const excluded=new Set(config.excluded||[]),hosts=(value.backups?.hosts||[]).map(h=>({...h,backup_required:!excluded.has(h.node+':'+h.vmid)}));
    // A node connection alert is relevant only while it has a monitored VM.
    const hypervisors=value._backup_scope_hypervisors||(value.needs_you||[]).filter(n=>n.kind==='hypervisor');
    const current=[...(value.needs_you||[]).filter(n=>n.kind!=='hypervisor'),...hypervisors];
    return {...value,_backup_scope_hypervisors:hypervisors,backups:{...value.backups,hosts},needs_you:current.filter(n=>n.kind!=='hypervisor'||hosts.some(h=>h.node===n.node&&h.backup_required))};
  }
  function assess(D, storage) {
    const hub = () => D.hub || {};
    const m = D.machine || {}, h = hub(), st = h.status || {}, bk = D.backups || {}, hosts = ((D.fleet || {}).hosts || []);
    // Ages are measured when status was observed, like the ages the service computes. A
    // re-render later must not age jobs that were healthy then into alerts nobody re-read.
    const seenAt = Date.parse(D._status?.observed_at || D.generated_at), at = Number.isFinite(seenAt) ? seenAt : Date.now();
    const ago = (iso) => iso ? (at - new Date(iso).getTime()) / 36e5 : null;
    const need = [], fresh = [], stale = [], waiting = [], queue = []; let cad;
    const late = (name, detail, ageH, cad, jump, cause) => {   // one thing against its cadence
      if (ageH == null || cad == null) return;
      if (ageH > 2 * cad) need.push({ state: "down", name, detail: `${detail} ${age(ageH)} ago, expected every ${age(cad)}`, age_h: ageH, jump, cause, order: 0 });
      else if (ageH > cad) stale.push({ state: "warn", name, detail: `${detail} ${age(ageH)} ago, expected every ${age(cad)}`, age_h: ageH, jump });
      else return true;
    };
    // Is the app you are looking at built from the source on this machine?
    // Nothing answered that until 2026-09-20, so one machine ran a 0.1 prototype for
    // months while the other moved through twenty-two builds. It always says something:
    // current is a quiet confirmation, behind is a thing to do, and a build with no
    // stamp says so rather than implying agreement it cannot check.
    const appInfo = m.app || {}, srcRev = (m.template_rev || "").split(" ")[0];
    if (appInfo.installed) {
      const label = `Sovereign ${appInfo.version || "?"} build ${appInfo.build || "?"}`;
      const jump = { view: "system" };
      if (!appInfo.source_commit) {
        stale.push({ state: "warn", name: "Update status unknown", detail: `This build of Sovereign predates update checking, so it cannot tell you whether it is current. Installing once will fix that permanently.`,
                     why: `The bundle records no source revision, so there is nothing to compare against this machine's source (${srcRev || "unknown"}).`,
                     action: "Update now", actionKind: "app-update", age_h: null, jump, cause: "app-unstamped" });
      } else if (!srcRev) {
        stale.push({ state: "warn", name: "Update status unknown", detail: `Sovereign ${appInfo.version || "?"} build ${appInfo.build || "?"} cannot be checked for updates right now.`,
                     why: "This machine's source revision could not be read, so the installed build has nothing to be compared against.", age_h: null, jump, cause: "app-source-unknown" });
      } else if (appInfo.source_commit.replace("+local", "") !== srcRev) {
        // Plainly: an update is ready. The revisions are evidence, so they belong in the
        // drawer with the rest of the evidence, not in the sentence that has to land first.
        need.push({ state: "warn", name: "Update available", detail: `A newer version of Sovereign is ready to install. You are running ${appInfo.version || "?"} build ${appInfo.build || "?"}.`,
                    why: `The installed app was built from source ${appInfo.source_commit}; this machine's source is now ${srcRev}.`,
                    action: "Update now",
                    actionKind: "app-update",
                    verify: "This row becomes \u201cUp to date\u201d once the new build is installed.",
                    age_h: null, jump, order: 1, cause: "app-behind" });
      } else {
        fresh.push({ state: "live", name: "Up to date", detail: `Sovereign ${appInfo.version || "?"} build ${appInfo.build || "?"} is the newest build of this machine's source.`,
                     why: `Built from source ${srcRev}, which is what this machine has.`,
                     age_h: null, jump, cause: "app-current" });
      }
    }
    // Permissions: where a lane's declared contract disagrees with itself or the law.
    // Every permission failure found on 2026-09-20 had this shape, and none of them was
    // hidden: a read wire nobody intended, a mirror gate no contract declared, a lane
    // running that the law never named. Nothing compared the contract with the reality.
    (D.lanes || []).forEach(l => (l.findings || []).filter(f => f.level === "warn").forEach(f => {
      stale.push({ state: "warn", name: `lane ${l.lane}`, detail: f.text,
                   why: "The lane's own contract is what grants a producer its read and write permissions; this one does not say what it should.",
                   action: `Open the lane's LANE.md and settle it: ${l.relative_path || "raw/workspaces/" + l.lane}/LANE.md`,
                   age_h: null, jump: { view: "tools", id: l.lane },
                   cause: "permission-drift", causeLabel: "have a permission their contract does not settle" });
    }));
    // What is waiting. The hub has always reported its queue depth and the app showed
    // none of it: a row saying "open Review" while 2,259 items sat unjudged and 2,451
    // more were deferred beyond the nightly cap. A number the owner cannot see is a
    // number he cannot act on, and the rate is what makes it mean something.
    const cov = st.coverage || {}, judgedRun = Number(st.judged) || 0;
    const waitingCount = Number(cov.unjudged_in_window) || 0;
    const strandedCount = Number(cov.stranded_pre_watermark) || 0;
    const deferredCount = Number(st.deferred) || 0;
    if (waitingCount > 0) {
      const nights = judgedRun > 0 ? Math.ceil(waitingCount / judgedRun) : null;
      queue.push({ state: "warn", name: "Waiting to be judged", age_h: null, jump: { view: "jobs", id: "hub:job:nightly" },
        detail: `${waitingCount.toLocaleString()} item${waitingCount === 1 ? "" : "s"} the curator has not read yet` +
                (nights ? `, about ${nights} night${nights === 1 ? "" : "s"} at ${judgedRun} a night.` : "."),
        why: `${(Number(cov.processable) || 0).toLocaleString()} items are eligible and ${(Number(cov.judged_ever) || 0).toLocaleString()} have ever been judged.` +
             (deferredCount ? ` ${deferredCount.toLocaleString()} of the waiting are deferred past each run's cap and carried to the next.` : ""),
        action: "Nothing is lost while it waits: the watermark is held below the oldest unjudged item.",
        cause: "queue-waiting" });
    }
    if (strandedCount > 0) {
      // Named separately because time alone never reaches it: the nightly judges newest
      // first, so this tail stays where it is until something goes after it deliberately.
      queue.push({ state: "warn", name: "Older than the watermark", age_h: null, jump: { view: "jobs", id: "hub:job:burndown" },
        detail: `${strandedCount.toLocaleString()} item${strandedCount === 1 ? "" : "s"} sit behind the point the curator started from and will not be reached by the nightly run.`,
        why: "The nightly judges the newest material first, so this tail is only read by a run that goes after it on purpose.",
        cause: "queue-stranded" });
    }
    // needs: failures, unreachable, the gate, unprotected machines
    const localHubFailures = new Map(h.via === 'local' ? Object.entries(h.jobs||{}).filter(([,j])=>j.source==='hub-runner'&&j.ts&&j.exit!=null&&j.exit!==0).map(([k,j])=>['com.sovereign.hub.'+k,j]) : []);
    const coveredLocalJob = j => {const receipt=localHubFailures.get(j.label);return receipt && receipt.exit===j.last_exit && Number.isFinite(j.last_run) && Date.parse(receipt.ts)/1000===j.last_run;};
    // A local job the service reports leads its sentence with the job's label. That row is the
    // job's one row: red and first when it failed, named and landing on the job. Every other
    // service row says what it is in its kind: name it, colour it and send it where its own
    // next step points.
    const hubName = h.hub_host || (m.hub_pointer || '').split(':')[0], tool = id => ((D.harnesses || []).find(x => x.id === id) || {}).name || id;
    const KIND_VIEW = { hypervisor: "backups", relay: "backups", "runner-stalled": "jobs", "runner-standing-down": "jobs" };
    const here = n => !n.host || n.host === m.host, labelOf = n => String(n.text || "").split(/[:\s]/)[0];
    const jobRow = n => (n.kind === "job" || n.kind === "xcode-license") && here(n) && !!labelOf(n), named = new Set((D.needs_you || []).filter(jobRow).map(labelOf));
    (D.needs_you || []).forEach((n, i) => { if(n.kind === "client-intake" || n.kind === "job" && here(n) && (D.jobs||[]).some(j=>coveredLocalJob(j)&&n.text?.startsWith(j.label+' last exited ')))return;
      const job = jobRow(n), down = n.kind === "xcode-license" || n.kind === "job" && / last exited /.test(n.text || "") || ["host", "hub", "runner-stalled"].includes(n.kind);
      need.push({ state: down ? "down" : "warn", name: job ? shortLabel(labelOf(n)) : n.harness ? tool(n.harness) : n.kind === "hub" ? "Hub" : /^runner-/.test(n.kind) ? "runner" : n.host || n.lane || n.node || n.kind,
        detail: n.text, why:n.why, failure_output:n.failure_output, action:n.action, url:n.url, verify:n.verify, age_h: null, need: i, order: down ? 0 : 1, cause: "need:" + n.kind,
        jump: n.harness ? {view:"tools",id:n.harness} : job ? {view:"jobs",id:labelOf(n)} : n.host ? {view:"hosts",id:n.host} : n.kind === "hub" ? {view:"hosts",id:hubName} : KIND_VIEW[n.kind] ? {view:KIND_VIEW[n.kind]} : null }); });
    // A client whose intake failed is one row, from the clients list, which disassociation
    // filters; the service's own client-intake row names it only inside a sentence.
    (D.clients || h.clients || []).filter(c => c.state === "error" || c.state === "rejected").forEach(c => need.push({ state: "down", name: String(c.client_id || "unknown"),
      detail: "Intake needs attention: " + (c.reason || "see rejected items in the hub receipt."), why: "What this client sent was received but not imported into raw.",
      action: "Open Sources → Map and inspect this client and its hub intake receipt. Correct the source or intake connection, then rerun the configured intake job.",
      verify: "Refresh after the next intake; the client reports imported.", age_h: null, jump: { view: "system" }, order: 0, cause: "intake-failed", causeLabel: "had their intake fail" }));
    (D.jobs || []).filter(j => !coveredLocalJob(j) && !named.has(j.label)).filter(j => j.last_exit != null && j.last_exit !== 0).forEach(j => need.push({ state: "down", name: shortLabel(j.label), detail: `failed its last run (exit ${j.last_exit}) on ${m.host}`, age_h: j.stderr_age_h, jump: { view: "jobs", id: j.label }, order: 0, cause: "job-failed" }));
    Object.entries(h.jobs || {}).filter(([, j]) => j.exit != null && j.exit !== 0).forEach(([k,j]) => {
      const health = hubJob(j,D), paused = health.state === 'paused', pending = paused || health.state === 'awaiting_verification';
      (pending ? waiting : need).push({state:health.tone,name:k,detail:j.health ? health.summary : `exited ${j.exit} on the hub`,
        why:health.why,failure_output:health.failure_output,action:health.action,verify:health.verify,age_h:ago(j.ts),jump:{view:'jobs',id:'hub:job:'+k},order:0,
        cause:paused?'job-paused':pending?'job-verifying':'job-failed'});
    });
    if (h.jobs_error) need.push({ state: "warn", name: "Hub jobs", detail: h.jobs_error, jump: { view: "jobs" }, order: 0, cause: "hub-jobs-unknown" });
    hosts.filter(x => x.net && x.net.online === false && !(D.needs_you||[]).some(n=>n.kind==="host"&&n.host===x.host)).forEach(x => need.push({ state: "down", name: x.host, detail: "This device cannot currently reach " + x.host + ".", why:"The reported network check failed; the cause is not confirmed.", action:"Check the device’s power and network connection, then inspect it in Sources → Devices.", verify:"Refresh; the device reports reachable.", age_h: null, jump: { view: "hosts", id: x.host }, order: 0, cause: "unreachable" }));
    if (h.reachable === false && !(D.needs_you||[]).some(n=>n.kind==='hub') && !hosts.some(x => x.host === hubName && x.net?.online === false))
      need.push({state:'down',name:'Hub',detail:'unreachable; review and acceptance could not be checked',jump:{view:'hosts',id:hubName},order:0});
    (bk.hosts || []).forEach(x => {
      const b=backupState(x);if(!b.issue)return;
      need.push({state:b.state,name:x.host,detail:b.text,age_h:x.last_dump_age_h,
        jump:{view:'backups',id:'bk:host:'+x.host},order:2,cause:b.issue,
        causeLabel:b.issue==='no-backup'?'have no completed backup':b.issue==='backup-unknown'?'have unknown backup status':b.issue==='backup-unscheduled'?'have no backup schedule':'have stale backups',
        why:b.issue==='backup-unknown'?(x.backup_errors||[]).join(' ')||b.text:b.text,
        action:'Open Backups → Copies and inspect this VM’s storage and job coverage in Proxmox.',
        verify:'Refresh after the storage check or next successful backup; confirm the recorded backup and schedule coverage.'});
    });
    // cadence: mirrors here, mirrors on every host, producer pushes, hub jobs, the snapshot
    (D.harnesses || []).forEach(x => { if (x.state !== "connected" || x.runs_on) return; const ah = x.run_age_h != null ? x.run_age_h : runAge(x.last_run, at), cad = intervalOf(x) / 3600;
      if (late(x.name || x.id, "mirror last ran", ah, cad, { view: "tools", id: x.id }, "mirror-late") === true && ah != null && ah <= cad) fresh.push({ state: "live", name: x.name || x.id, detail: `pulled ${age(ah)} ago on ${m.host}`, age_h: ah, jump: { view: "tools", id: x.id }, cause: "pull:" + m.host, host: m.host }); });
    // a remote mirror's heartbeat reaches this copy through the exchange and the sync, so its
    // observable cadence is about an hour, not its own 15 minutes
    // A remote mirror's heartbeat reaches this copy through the exchange and the sync, so
    // its observable cadence is about an hour, not its own fifteen minutes.
    const hubLanes = h.lanes || {};
    hosts.filter(x => x.host !== m.host).forEach(x => (x.harnesses || []).forEach(t => {
      const here = t.run_age_h, there = (hubLanes[t.lane] || {}).age_h, ah = [here, there].filter(v => v != null).length ? Math.min(...[here, there].filter(v => v != null)) : null;
      if (late(`${t.harness} on ${x.host}`, "mirror last ran", ah, cad = 1, { view: "hosts", id: x.host }, "mirror-late") === true) fresh.push({ state: "live", name: `${t.harness} on ${x.host}`, detail: `pulled ${age(ah)} ago`, age_h: ah, jump: { view: "hosts", id: x.host }, cause: "pull:" + x.host, host: x.host }); }));
    // Is THIS copy behind the hub? Compare the same lane's newest content in both places.
    // It used to subtract a hub lane's age from a REMOTE HOST'S harness run age, which are
    // not two views of one thing: a mirror that had not run in sixteen days on another
    // machine was reported here as "this copy is 16d behind the hub", which was never true.
    // Done properly this is the detector that catches the sync dropping file types it does
    // not carry, which on 2026-09-20 had stranded 49 documents on a single machine.
    // The curator's own lane is exempt: the law makes its operational state hub-authoritative,
    // so this copy is meant to lag it.
    let lag = 0, lagLane = null;
    const curatorLane = h.lane || "archivist";
    (D.lanes || []).forEach(l => {
      if (l.retired || l.lane === curatorLane) return;
      const here = l.vault_age_h, there = l.hub_age_h;
      if (here != null && there != null && here - there > lag) { lag = here - there; lagLane = l.lane; }
    });
    if (lag > 1) stale.push({ state: "warn", name: "this copy", detail: `${age(lag)} behind the hub on ${lagLane} (${(D.obsidian || {}).sync || "sync"} has not carried everything)`, age_h: lag, jump: { view: "backups", id: "bk:obsidian" } });
    (bk.lanes || []).forEach(l => {
      const ah = ago(l.pushed), jump = { view: "backups", id: "bk:lane:" + l.lane };
      if (l.delivery === "waiting") {
        need.push({ state: "warn", name: `lane ${l.lane}`, detail: "pushed, awaiting hub acceptance", age_h: ah, jump, order: 1 });
      } else if (l.delivery === "accepted" && late(`lane ${l.lane}`, "last source commit", ah, 24, jump, "lane-late") === true) {
        fresh.push({ state: "live", name: `lane ${l.lane}`, detail: `source from ${age(ah)} ago is included on the hub`, age_h: ah, jump });
      }
    });
    Object.entries(h.jobs || {}).forEach(([k, j]) => { const cad = j.cadence_s ? j.cadence_s / 3600 : HUB_CADENCE_H[k]; if (!cad || j.exit) return; late(k, "last completed", ago(j.ts), cad, { view: "jobs", id: "hub:job:" + k }, "hub-job-late"); });
    if (bk.snapshots) late("daily snapshot", "last taken", bk.snapshots.newest_age_h, 24, { view: "backups", id: "bk:snapshots" }, "snapshot-late");
    // fresh: events, not states
    const landed = landedToday(D);
    if (landed) fresh.unshift({ state: "live", name: "archive", detail: `${landed} card${landed === 1 ? "" : "s"} landed today`, age_h: null, jump: { view: "archive", id: "week:" + isoWeekKey(new Date(at)) } });
    if (st.judged != null) fresh.unshift({ state: "live", name: "judge", detail: `kept ${num(st.new_proposals)} of ${num(st.judged)} last run`, age_h: h.status_age_h, jump: { view: "jobs", id: "hub:judge" } });
    let prev = {}; try { prev = JSON.parse(storage.getItem("sov.online") || "{}"); } catch (e) {}
    const now = {}; hosts.forEach(x => { if (x.net && x.net.online != null) now[x.host] = x.net.online; if (x.net && x.net.online && prev[x.host] === false) fresh.push({ state: "live", name: x.host, detail: "came back", age_h: null, jump: { view: "hosts", id: x.host } }); });
    try { storage.setItem("sov.online", JSON.stringify(now)); } catch (e) {}
    // Derived alerts follow the same explanation contract as service-produced rows.
    const where = v => ({ tools: "Sources", hosts: "Sources → Devices", system: "Sources → Map", backups: "Backups → Copies" })[v] || "Settings → Jobs";
    for(const r of [...need,...stale]){
      const place=where(r.jump?.view);
      const guidance=r.cause==='no-backup'?
        ['The node returned no recorded backup dump for this VM. A configured job alone does not prove a completed backup.', 'Open Backups → Copies and inspect this VM’s backup job and last dump. Arrange a backup with the node administrator if none exists.', 'Refresh after the next successful backup; the VM shows a recent last backup age.']:
        r.detail==='pushed, awaiting hub acceptance'?
        ['The source commit has been published but is not yet included in the hub’s observed main branch.', 'Open Backups → Copies, select this contribution lane and inspect its source commit and exchange status.', 'Refresh after the hub accepts the source commit; the lane reads accepted.']:
        r.cause==='unreachable'||r.name==='Hub'?
        ['The network or hub status check did not succeed; the underlying cause is unconfirmed.', 'Open Sources → Devices and check this device’s power, network and configured connection.', 'Refresh; the device reports reachable and the hub returns a current queue.']:
        r.need!=null?
        ['This older status report did not provide a separate cause.', 'Open '+place+' and inspect the reported condition. Ask the status-service maintainer to supply diagnostic details if the summary is insufficient.', 'Refresh after resolving the reported condition; this attention item clears.']:
        ['The latest recorded run or contribution does not meet the reported result or cadence.', 'Open '+place+' and inspect '+r.name+' and its most recent log or contribution record.', 'Refresh after a successful run or contribution; its result and observation time meet the reported cadence.'];
      r.why ||= guidance[0];r.action ||= guidance[1];r.verify ||= guidance[2];
    }
    fresh.sort((p, q) => (p.age_h == null ? -1 : p.age_h) - (q.age_h == null ? -1 : q.age_h));
    const worse = (p, q) => p.order - q.order || (p.state === "down" ? 0 : 1) - (q.state === "down" ? 0 : 1);   // worst state first
    need.sort((p, q) => worse(p, q) || (q.age_h || 0) - (p.age_h || 0));
    stale.sort((p, q) => (q.age_h || 0) - (p.age_h || 0));
    // one row per repeated cause; the drawer lists the members
    const collapse = (list, mk) => {
      const out = [], byCause = {};
      list.forEach(r => { if (!r.cause || r.need != null) { out.push(r); return; } (byCause[r.cause] = byCause[r.cause] || []).push(r); });
      Object.entries(byCause).forEach(([cause, rows]) => { if (rows.length < 2) out.push(rows[0]); else out.push(Object.assign(mk(cause, rows), { group: cause, members: rows })); });
      return out;
    };
    const needG = collapse(need, (cause, rows) => {
      const label = rows[0].causeLabel || (cause === "job-failed" ? "failed their last run" : cause === "unreachable" ? "are unreachable" : cause === "mirror-late" ? "are past twice their mirror cadence" : "need a look");
      // One noun per thing: a job, a source (a tool or lane that feeds the archive), or a device.
      const noun = cause === "job-failed" || cause === "hub-job-late" ? "jobs" : cause === "mirror-late" || cause === "lane-late" ? "sources" : "devices";
      return { state: rows.some(r => r.state === "down") ? "down" : "warn", name: `${rows.length} ${noun}`,
        detail: `${label}: ${rows.map(r => r.name).join(", ")}`, why:rows.some(r=>r.failure_output)?'Recorded failure details for each job are shown below.':rows[0].why, action:'Inspect each listed item in '+where(rows[0].jump?.view)+'. '+rows[0].action, verify:rows[0].verify, age_h: null, order: rows[0].order };
    }).sort(worse);
    const freshG = collapse(fresh, (cause, rows) => { const newest = Math.min(...rows.map(r => r.age_h == null ? Infinity : r.age_h));
      return { state: "live", name: `${rows.length} mirrors`, detail: `pulled on ${rows[0].host}, newest ${age(newest)} ago`, age_h: isFinite(newest) ? newest : null, order: 1 }; });
    freshG.sort((p, q) => (p.age_h == null ? -1 : p.age_h) - (q.age_h == null ? -1 : q.age_h));
    return { need: needG, fresh: freshG, stale, waiting, queue, completeness: completeness(D) };
  }
  const safeURL=value=>{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&u.hostname?u.href:null}catch(_){return null}};
  function caption(status) {
    const s=status?._status||{},stamp=s.observed_at||status?.generated_at;
    const observed=Date.parse(stamp),minutes=Number.isFinite(observed)?Math.max(0,Math.floor((Date.now()-observed)/60000)):null;
    const budget=s.budget_s||window.sovStatusBudget;
    if(!status?.machine&&!status?.error)return 'Checking the connected system'+(budget?', up to '+budget+' seconds':'')+'.';
    const age=minutes===null?'Observation time unknown':'Observed '+minutes+' min ago';
    return age+(s.pending?', refreshing':s.error?', refresh failed':'')+(Number.isFinite(s.duration_s)?' · Status took '+s.duration_s.toFixed(1)+' s':'');
  }
  function retain(previous, next) {
    if(next.error&&previous?.machine)return {...previous,_status:{...previous._status,pending:false,stale:true,error:next.error},request:next.request};
    return associations(next);
  }
  // Keep raw status and archive history intact. Every app surface uses this projection.
  function associations(value) {
    value=backupScope(value);
    const retired=new Set((value?.harnesses||[]).filter(h=>h.state==='removed').map(h=>h.lane));
    if(retired.size)value={...value,
      lanes:(value.lanes||[]).map(l=>({...l,retired:retired.has(l.lane),associated:retired.has(l.lane)?false:l.associated})),
      fleet:{...value.fleet,hosts:(value.fleet?.hosts||[]).map(h=>({...h,harnesses:(h.harnesses||[]).filter(t=>!retired.has(t.lane)),lanes:(h.lanes||[]).filter(l=>!retired.has(l.lane))}))},
      backups:{...value.backups,lanes:(value.backups?.lanes||[]).filter(l=>!retired.has(l.lane))}};
    const config=value?.device_associations;
    if(!config?.available||config.scope!==value.machine?.vault)return value;
    const key=name=>String(name||'').toLowerCase();
    const protectedHosts=new Set((config.protected_hosts||[]).map(key));
    const excluded=new Set((config.disassociated||[]).map(key).filter(n=>!protectedHosts.has(n)));
    const fleet=value.fleet||{},hosts=[...(fleet.hosts||[]),...(fleet.disassociated||[])];
    const unique=[...new Map(hosts.map(h=>[key(h.host),h])).values()];
    const disassociated=unique.filter(h=>excluded.has(key(h.host))).map(h=>({...h,associated:false}));
    for(const name of config.disassociated||[])if(excluded.has(key(name))&&!unique.some(h=>key(h.host)===key(name)))
      disassociated.push({host:name,associated:false,lanes:[],harnesses:[],meta:{},net:{online:null}});
    const hiddenLanes=new Set(disassociated.flatMap(h=>[...(h.lanes||[]),...(h.harnesses||[])].map(l=>l.lane)));
    for(const lane of value.lanes||[])if(excluded.has(key(lane.host)))hiddenLanes.add(lane.lane);
    const hostVisible=r=>!excluded.has(key(r.host||r.client_id));
    const laneVisible=r=>!hiddenLanes.has(r.lane);
    const hub=value.hub||{},backups=value.backups||{};
    return {...value,
      fleet:{...fleet,hosts:unique.filter(hostVisible).map(h=>({...h,associated:true})),disassociated},
      needs_you:(value.needs_you||[]).filter(n=>hostVisible(n)&&laneVisible(n)),
      harnesses:(value.harnesses||[]).filter(h=>!excluded.has(key(h.runs_on))),
      lanes:(value.lanes||[]).map(l=>({...l,associated:laneVisible(l)&&!l.retired})),
      clients:(value.clients||hub.clients||[]).filter(hostVisible),
      hub:{...hub,clients:(hub.clients||[]).filter(hostVisible)},
      backups:{...backups,hosts:(backups.hosts||[]).filter(hostVisible),lanes:(backups.lanes||[]).filter(laneVisible)}
    };
  }
  function contributionIssue(lane) {
    if(lane.acceptance_issue)return lane.acceptance_issue;
    return {text:'Hub acceptance is unknown for '+lane.lane+'.',
      why:lane.delivery==='unknown'?'The hub could not verify whether the source commit is included.':'The connected status service did not report an acceptance result.',
      action:'Open Backups → Copies and inspect this lane’s source commit and hub connection. If the service is older, ask its maintainer to update it, then refresh.',
      verify:'The lane reports accepted or waiting after refresh. Only accepted confirms inclusion on the hub.'};
  }
  // A row's reason in two or three words. The sentence stays in its detail, said once.
  // No short form means the caller shows the sentence clipped to one line.
  function brief(r) {
    const c = r.cause || r.group || "";
    if (c === "need:gate") return "waiting";
    if (c === "unreachable" || c === "need:host" || r.name === "Hub") return "unreachable";
    // A job the status service reports: it either failed, or ran and wrote to its error log.
    if (c === "need:job") return /error output/.test(r.detail || "") ? "errors logged" : /last exited|failed/.test(r.detail || "") ? "failed" : "";
    if (c === "job-failed") return "failed";
    if (c === "intake-failed") return "intake failed";
    if (["mirror-late", "lane-late", "hub-job-late", "snapshot-late"].includes(c)) return r.age_h != null ? "silent " + age(r.age_h) : "late";
    if (c === "no-backup") return "no backup";
    if (c === "backup-stale") return "backup stale";
    if (c === "backup-unscheduled") return "not scheduled";
    if (c === "backup-unknown" || c === "need:hypervisor") return "backup unknown";
    if (c === "need:xcode-license") return "cannot start";
    if (c === "need:runner-stalled") return "stalled";
    if (c === "need:runner-standing-down") return "standing down";
    if (c === "app-behind") return "ready to install";
    if (c === "app-unstamped" || c === "app-source-unknown") return "cannot be checked";
    if (c === "permission-drift") return "permission unsettled";
    if (c === "job-paused") return "paused";
    if (c === "job-verifying") return "verifying";
    if (c === "hub-jobs-unknown") return "unknown";
    if (r.detail === "pushed, awaiting hub acceptance") return "awaiting hub";
    return "";
  }
  // The verdict: one sentence and the worst state, for the menu-bar crown and the Glance,
  // from the same assessment wherever the window is.
  function verdict(D, storage) {
    if (D?._status?.error || D?.error) return { state: "down", text: D._status?.error || D.error };
    if (D?._status?.pending) return { state: "warn", text: caption(D) };
    if (!D?.machine?.connected) return { state: "idle", text: "Not connected." };
    const A = assess(D, storage), st = (D.hub || {}).status || {}, hosts = ((D.fleet || {}).hosts || []);
    const down = A.need.filter(r => r.state === "down");
    // A service row's detail is already a sentence about its thing; a derived row's is not.
    const say = f => (f.group ? f.name + " " + f.detail.split(":")[0] : f.need != null ? f.detail : f.name + " " + f.detail).replace(/\.$/, "");
    let state, text;
    if (down.length) { state = "down"; text = `Attention: ${say(down[0])}${down.length > 1 ? `, and ${down.length - 1} more` : ""}.`; }
    else if (A.need.length) { state = "warn"; text = `${A.need.length} thing${A.need.length === 1 ? "" : "s"} need${A.need.length === 1 ? "s" : ""} you: ${say(A.need[0])}.`; }
    else if (A.waiting.length) { state = "idle"; text = `${A.waiting.length} awaiting verification. No action required while the next run is pending.`; }
    else if (A.stale.length) { state = "warn"; text = `Stale: ${A.stale[0].name} ${A.stale[0].detail}.`; }
    else {
      state = "live";
      const landed = landedToday(D);
      const fact = landed ? `${landed} card${landed === 1 ? "" : "s"} landed today` : st.judged != null ? `The judge kept ${num(st.new_proposals)} of ${num(st.judged)} last run` : `${hosts.filter(x => x.net && x.net.online).length} devices up`;
      text = `All good. ${fact}.`;
    }
    return { state, text: text.replace(/\.\.$/, ".") };
  }
  // When the status on screen was observed, as a clock time. The full caption (how long
  // ago, how long the check took) is evidence for a tooltip, never a line of the page.
  function seen(status) {
    const s = status?._status || {}, stamp = Date.parse(s.observed_at || status?.generated_at);
    if ((!status?.machine && !status?.error) || s.pending) return "checking…";
    if (s.error || status?.error) return "refresh failed";
    return Number.isFinite(stamp) ? new Date(stamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  }
  return {assess, verdict, backupState, backupScope, hubJob, shortLabel, safeURL, caption, retain, contributionIssue, associations, brief, seen, week: isoWeekKey};
})();
