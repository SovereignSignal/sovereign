'use strict';
// Shared assessment for Home, Review, Operations and menu-bar Glance.
window.SovStatus = (() => {
  const age = (h) => h == null ? "–" : h < 1 ? Math.max(1, Math.round(h * 60)) + "m" : h < 48 ? (Math.round(h * 10) / 10) + "h" : Math.round(h / 24) + "d";

  const num = (n) => n == null ? "?" : Number(n).toLocaleString();

  const runAge = (s) => { const m = /Last run: (\S+)/.exec(s || ""); if (!m) return null; const t = Date.parse(m[1]); return isNaN(t) ? null : (Date.now() - t) / 36e5; };

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
  const shortLabel = (l) => String(l).replace(/^com\.[a-z]+\.(connector|cron)\./, "");
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
    return {...health, state, summary, action, tone:state === 'healthy' ? 'live' : state === 'needs_attention' ? 'down' : '',
      label:state === 'awaiting_verification' ? 'Awaiting verification' : state === 'needs_attention' ? 'Needs attention' : state === 'healthy' ? 'Succeeded' : 'Unknown'};
  }
  function assess(D, storage) {
    const hub = () => D.hub || {}, arch = () => D.archive || {};
    const m = D.machine || {}, h = hub(), st = h.status || {}, bk = D.backups || {}, hosts = ((D.fleet || {}).hosts || []);
    const ago = (iso) => iso ? (Date.now() - new Date(iso).getTime()) / 36e5 : null;
    const need = [], fresh = [], stale = [], waiting = []; let cad;
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
    // needs: failures, unreachable, the gate, unprotected machines
    const localHubFailures = new Map(h.via === 'local' ? Object.entries(h.jobs||{}).filter(([,j])=>j.source==='hub-runner'&&j.ts&&j.exit!=null&&j.exit!==0).map(([k,j])=>['com.sovereign.hub.'+k,j]) : []);
    const coveredLocalJob = j => {const receipt=localHubFailures.get(j.label);return receipt && receipt.exit===j.last_exit && Number.isFinite(j.last_run) && Date.parse(receipt.ts)/1000===j.last_run;};
    (D.needs_you || []).forEach((n, i) => { if(n.kind === "job" && (!n.host||n.host===m.host) && (D.jobs||[]).some(j=>coveredLocalJob(j)&&n.text?.startsWith(j.label+' last exited ')))return; need.push({ state: "warn", name: n.host || n.lane || n.node || n.kind, detail: n.text, why:n.why, action:n.action, url:n.url, verify:n.verify, age_h: null, need: i, order: n.kind === "host" ? 0 : 1, cause: "need:" + n.kind, jump:n.host?{view:"hosts",id:n.host}:null }); });
    (D.jobs || []).filter(j => !coveredLocalJob(j)).filter(j => j.last_exit != null && j.last_exit !== 0).forEach(j => need.push({ state: "down", name: shortLabel(j.label), detail: `failed its last run (exit ${j.last_exit}) on ${m.host}`, age_h: j.stderr_age_h, jump: { view: "jobs", id: j.label }, order: 0, cause: "job-failed" }));
    Object.entries(h.jobs || {}).filter(([, j]) => j.exit != null && j.exit !== 0).forEach(([k,j]) => {
      const health = hubJob(j,D), pending = health.state === 'awaiting_verification';
      (pending ? waiting : need).push({state:health.tone,name:k,detail:j.health ? health.summary : `exited ${j.exit} on the hub`,
        why:health.why,action:health.action,verify:health.verify,age_h:ago(j.ts),jump:{view:'jobs',id:'hub:job:'+k},order:0,cause:pending?'job-verifying':'job-failed'});
    });
    if (h.jobs_error) need.push({ state: "warn", name: "Hub jobs", detail: h.jobs_error, jump: { view: "jobs" }, order: 0, cause: "hub-jobs-unknown" });
    hosts.filter(x => x.net && x.net.online === false && !(D.needs_you||[]).some(n=>n.kind==="host"&&n.host===x.host)).forEach(x => need.push({ state: "down", name: x.host, detail: "This device cannot currently reach " + x.host + ".", why:"The reported network check failed; the cause is not confirmed.", action:"Check the device’s power and network connection, then inspect it in Operations → Hosts.", verify:"Refresh; the device reports reachable.", age_h: null, jump: { view: "hosts", id: x.host }, order: 0, cause: "unreachable" }));
    const hubName = h.hub_host || (m.hub_pointer || '').split(':')[0];
    if (h.reachable === false && !(D.needs_you||[]).some(n=>n.kind==='hub') && !hosts.some(x => x.host === hubName && x.net?.online === false))
      need.push({state:'down',name:'Hub',detail:'unreachable; review and acceptance could not be checked',jump:{view:'jobs'},order:0});
    (bk.hosts || []).filter(x => x.reachable && x.last_dump_age_h == null).forEach(x => need.push({ state: "warn", name: x.host, detail: x.jobs===0?`no backup job on ${x.node}`:`no completed backup reported on ${x.node}`, age_h: null, jump: { view: "backups", id: "bk:host:" + x.host }, order: 2, cause: "no-backup", causeLabel: "have no completed backup" }));
    // cadence: mirrors here, mirrors on every host, producer pushes, hub jobs, the snapshot
    (D.harnesses || []).forEach(x => { if (x.state !== "connected" || x.runs_on) return; const ah = x.run_age_h != null ? x.run_age_h : runAge(x.last_run), cad = intervalOf(x) / 3600;
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
    const today = new Date().toISOString().slice(0, 10), a = arch(), landed = (a.cards || []).filter(c => c.created === today).length;
    if (landed) fresh.unshift({ state: "live", name: "archive", detail: `${landed} card${landed === 1 ? "" : "s"} landed today`, age_h: null, jump: { view: "archive", id: "week:" + isoWeekKey(new Date()) } });
    if (st.judged != null) fresh.unshift({ state: "live", name: "judge", detail: `kept ${num(st.new_proposals)} of ${num(st.judged)} last run`, age_h: h.status_age_h, jump: { view: "jobs", id: "hub:judge" } });
    let prev = {}; try { prev = JSON.parse(storage.getItem("sov.online") || "{}"); } catch (e) {}
    const now = {}; hosts.forEach(x => { if (x.net && x.net.online != null) now[x.host] = x.net.online; if (x.net && x.net.online && prev[x.host] === false) fresh.push({ state: "live", name: x.host, detail: "came back", age_h: null, jump: { view: "hosts", id: x.host } }); });
    try { storage.setItem("sov.online", JSON.stringify(now)); } catch (e) {}
    // Derived alerts follow the same explanation contract as service-produced rows.
    for(const r of [...need,...stale]){
      const place=r.jump?.view==='tools'?'Tools':r.jump?.view==='hosts'?'Hosts':r.jump?.view==='backups'?'Backups':'Jobs';
      const guidance=r.cause==='no-backup'?
        ['The node returned no recorded backup dump for this VM. A configured job alone does not prove a completed backup.', 'Open Operations → Backups and inspect this VM’s backup job and last dump. Arrange a backup with the node administrator if none exists.', 'Refresh after the next successful backup; the VM shows a recent last backup age.']:
        r.detail==='pushed, awaiting hub acceptance'?
        ['The source commit has been published but is not yet included in the hub’s observed main branch.', 'Open Operations → Backups, select this contribution lane and inspect its source commit and exchange status.', 'Refresh after the hub accepts the source commit; the lane reads accepted.']:
        r.cause==='unreachable'||r.name==='Hub'?
        ['The network or hub status check did not succeed; the underlying cause is unconfirmed.', 'Open Operations → Hosts and check this device’s power, network and configured connection.', 'Refresh; the device reports reachable and the hub returns a current queue.']:
        r.need!=null?
        ['This older status report did not provide a separate cause.', 'Open Operations → '+place+' and inspect the reported condition. Ask the status-service maintainer to supply diagnostic details if the summary is insufficient.', 'Refresh after resolving the reported condition; this attention item clears.']:
        ['The latest recorded run or contribution does not meet the reported result or cadence.', 'Open Operations → '+place+' and inspect '+r.name+' and its most recent log or contribution record.', 'Refresh after a successful run or contribution; its result and observation time meet the reported cadence.'];
      r.why ||= guidance[0];r.action ||= guidance[1];r.verify ||= guidance[2];
    }
    fresh.sort((p, q) => (p.age_h == null ? -1 : p.age_h) - (q.age_h == null ? -1 : q.age_h));
    need.sort((p, q) => p.order - q.order || (q.age_h || 0) - (p.age_h || 0));
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
      return { state: rows.some(r => r.state === "down") ? "down" : "warn", name: `${rows.length} ${cause === "job-failed" || cause === "hub-job-late" ? "jobs" : "machines"}`,
        detail: `${label}: ${rows.slice(0, 2).map(r => r.name).join(", ")}${rows.length > 2 ? " and " + (rows.length - 2) + " more" : ""}`, why:rows[0].why, action:'Inspect each listed item in Operations → '+(rows[0].jump?.view==='backups'?'Backups':rows[0].jump?.view==='hosts'?'Hosts':rows[0].jump?.view==='tools'?'Tools':'Jobs')+'. '+rows[0].action, verify:rows[0].verify, age_h: null, order: rows[0].order };
    }).sort((p, q) => p.order - q.order);
    const freshG = collapse(fresh, (cause, rows) => { const newest = Math.min(...rows.map(r => r.age_h == null ? Infinity : r.age_h));
      return { state: "live", name: `${rows.length} mirrors`, detail: `pulled on ${rows[0].host}, newest ${age(newest)} ago`, age_h: isFinite(newest) ? newest : null, order: 1 }; });
    freshG.sort((p, q) => (p.age_h == null ? -1 : p.age_h) - (q.age_h == null ? -1 : q.age_h));
    return { need: needG, fresh: freshG, stale, waiting };
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
      action:'Open Operations → Backups and inspect this lane’s source commit and hub connection. If the service is older, ask its maintainer to update it, then refresh.',
      verify:'The lane reports accepted or waiting after refresh. Only accepted confirms inclusion on the hub.'};
  }
  return {assess, hubJob, shortLabel, safeURL, caption, retain, contributionIssue, associations};
})();
