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
  function assess(D, storage) {
    const hub = () => D.hub || {}, arch = () => D.archive || {};
    const m = D.machine || {}, h = hub(), st = h.status || {}, bk = D.backups || {}, hosts = ((D.fleet || {}).hosts || []);
    const ago = (iso) => iso ? (Date.now() - new Date(iso).getTime()) / 36e5 : null;
    const need = [], fresh = [], stale = []; let cad;
    const late = (name, detail, ageH, cad, jump, cause) => {   // one thing against its cadence
      if (ageH == null || cad == null) return;
      if (ageH > 2 * cad) need.push({ state: "down", name, detail: `${detail} ${age(ageH)} ago, expected every ${age(cad)}`, age_h: ageH, jump, cause, order: 0 });
      else if (ageH > cad) stale.push({ state: "warn", name, detail: `${detail} ${age(ageH)} ago, expected every ${age(cad)}`, age_h: ageH, jump });
      else return true;
    };
    // needs: failures, unreachable, the gate, unprotected machines
    (D.needs_you || []).forEach((n, i) => need.push({ state: "warn", name: n.host || n.lane || n.node || n.kind, detail: n.text, why:n.why, action:n.action, url:n.url, verify:n.verify, age_h: null, need: i, order: n.kind === "host" ? 0 : 1, cause: "need:" + n.kind, jump:n.host?{view:"hosts",id:n.host}:null }));
    (D.jobs || []).filter(j => j.last_exit != null && j.last_exit !== 0).forEach(j => need.push({ state: "down", name: shortLabel(j.label), detail: `failed its last run (exit ${j.last_exit}) on ${m.host}`, age_h: j.stderr_age_h, jump: { view: "jobs", id: j.label }, order: 0, cause: "job-failed" }));
    Object.entries(h.jobs || {}).filter(([, j]) => j.exit != null && j.exit !== 0).forEach(([k, j]) => need.push({ state: "down", name: k, detail: `exited ${j.exit} on the hub`, age_h: ago(j.ts), jump: { view: "jobs", id: "hub:job:" + k }, order: 0, cause: "job-failed" }));
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
    // The hub sees its own lanes and the producers' merges first; this copy sees them through the
    // sync. Take the fresher of the two views, and name the lag itself when this copy falls behind.
    const hubLanes = h.lanes || {}; let lag = 0, lagLane = null;
    hosts.filter(x => x.host !== m.host).forEach(x => (x.harnesses || []).forEach(t => {
      const here = t.run_age_h, there = (hubLanes[t.lane] || {}).age_h, ah = [here, there].filter(v => v != null).length ? Math.min(...[here, there].filter(v => v != null)) : null;
      if (here != null && there != null && here - there > lag) { lag = here - there; lagLane = t.lane; }
      if (late(`${t.harness} on ${x.host}`, "mirror last ran", ah, cad = 1, { view: "hosts", id: x.host }, "mirror-late") === true) fresh.push({ state: "live", name: `${t.harness} on ${x.host}`, detail: `pulled ${age(ah)} ago`, age_h: ah, jump: { view: "hosts", id: x.host }, cause: "pull:" + x.host, host: x.host }); }));
    if (lag > 1) stale.push({ state: "warn", name: "this copy", detail: `${age(lag)} behind the hub (${(D.obsidian || {}).sync || "sync"}); ${lagLane} is the widest gap`, age_h: lag, jump: { view: "backups", id: "bk:obsidian" } });
    (bk.lanes || []).forEach(l => {
      const ah = ago(l.pushed), jump = { view: "backups", id: "bk:lane:" + l.lane };
      if (l.delivery === "waiting") {
        need.push({ state: "warn", name: `lane ${l.lane}`, detail: "pushed, awaiting hub acceptance", age_h: ah, jump, order: 1 });
      } else if (l.delivery === "accepted" && late(`lane ${l.lane}`, "last source commit", ah, 24, jump, "lane-late") === true) {
        fresh.push({ state: "live", name: `lane ${l.lane}`, detail: `source from ${age(ah)} ago is included on the hub`, age_h: ah, jump });
      }
    });
    Object.entries(h.jobs || {}).forEach(([k, j]) => { const cad = HUB_CADENCE_H[k]; if (!cad || j.exit) return; late(k, "last ran", ago(j.ts), cad, { view: "jobs", id: "hub:job:" + k }, "hub-job-late"); });
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
    return { need: needG, fresh: freshG, stale };
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
    return next;
  }
  function contributionIssue(lane) {
    if(lane.acceptance_issue)return lane.acceptance_issue;
    return {text:'Hub acceptance is unknown for '+lane.lane+'.',
      why:lane.delivery==='unknown'?'The hub could not verify whether the source commit is included.':'The connected status service did not report an acceptance result.',
      action:'Open Operations → Backups and inspect this lane’s source commit and hub connection. If the service is older, ask its maintainer to update it, then refresh.',
      verify:'The lane reports accepted or waiting after refresh. Only accepted confirms inclusion on the hub.'};
  }
  return {assess, shortLabel, safeURL, caption, retain, contributionIssue};
})();
