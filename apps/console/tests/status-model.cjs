const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const box = {window:{},URL}; vm.createContext(box);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/status-model.js'),'utf8'),box);
const assess = box.window.SovStatus.assess;
// Runner receipts must use their declared cadence and surface failed/unknown reads.
const oldRun = new Date(Date.now() - 3600000).toISOString();
assert.equal(assess({hub:{jobs:{'fleet-watch':{ts:oldRun,exit:0,cadence_s:300}}}}).need[0].state,'down');
assert.equal(assess({hub:{jobs:{autocommit:{ts:oldRun,exit:1,cadence_s:86400}}}}).need[0].cause,'job-failed');
assert.equal(assess({hub:{jobs:{nightly:{ts:null,exit:null,cadence_s:86400}}}}).need.length,0);
assert.equal(assess({hub:{jobs_error:'Receipts unavailable'}}).need[0].state,'warn');
const lane = delivery => ({lane:'producer',pushed:'2000-01-01T00:00:00Z',...(delivery===undefined?{}:{delivery})});
for(const delivery of [undefined,null,'','unrecognized']) {
 const a=assess({backups:{lanes:[lane(delivery)]}});
 assert.equal(a.need.length,0); assert.equal(a.stale.length,0); assert.equal(a.fresh.length,0);
}
assert.equal(assess({backups:{lanes:[lane('waiting')]}}).need[0].state,'warn');
assert.equal(assess({backups:{lanes:[lane('accepted')]}}).need[0].state,'down');
assert.equal(assess({backups:{lanes:[{...lane('accepted'),pushed:new Date().toISOString()}]}}).fresh[0].state,'live');
const failures={machine:{host:'local',hub_pointer:'hub:/archive'},jobs:[{label:'job-a',last_exit:1},{label:'job-b',last_exit:2}],fleet:{hosts:[{host:'hub',net:{online:false}}]},hub:{reachable:false},backups:{lanes:[lane()]}};
const result=assess(failures);assert.equal(result.need.length,2);
assert.equal(result.need.filter(x=>x.state==='down').length,2);
assert.equal(result.need.find(x=>x.group==='job-failed').members.length,2);
assert.equal(assess({hub:{reachable:false}}).need[0].state,'down');
console.log('Status assessment: 4 unknown variants neutral; waiting, accepted freshness, failures, grouping and hub dedupe passed.');

// Ages are measured at the observation. Re-rendering an hour-old status (a row opened,
// a refresh pending or failed) must not age healthy jobs and mirrors into alerts.
const hourAgo=new Date(Date.now()-3600000).toISOString();
const observedHealthy={generated_at:hourAgo,_status:{observed_at:hourAgo},machine:{host:'here'},
 hub:{jobs:{'verdict-poll':{ts:hourAgo,exit:0,cadence_s:60}}},harnesses:[{id:'tool',name:'tool',state:'connected',cadence_s:900,last_run:'Last run: '+hourAgo}],
 backups:{lanes:[{lane:'producer',delivery:'accepted',pushed:hourAgo}]}};
assert.equal(assess(observedHealthy).need.length,0,'healthy when observed stays healthy');
assert.equal(assess(observedHealthy).stale.length,0);
assert.equal(assess({...observedHealthy,_status:{}}).need.length,0,'generated_at stands in for the observation time');
console.log('Ages: measured at the observation, never at render time.');

const model=box.window.SovStatus;
const liveProgress={phase:'judging',active:true,summary:'Judging 3/50',checked_at:Date.now()/1000,no_progress_s:90};
const progressing=model.hubJob({exit:0,progress:liveProgress});
assert.equal(progressing.label,'Running');
assert.match(progressing.summary,/Judging 3\/50.*Last run succeeded/);
assert.equal(model.hubJob({exit:1,progress:liveProgress}).state,'needs_attention');
assert.equal(model.hubJob({exit:1,progress:liveProgress}).tone,'down');
assert.equal(model.hubJob({exit:0,progress:{...liveProgress,phase:'waiting_model'}}).label,'Waiting');
assert.equal(model.hubJob({exit:0,progress:liveProgress},{_status:{stale:true}}).label,'Refresh progress');
assert.equal(model.hubJob({exit:0,progress:{...liveProgress,checked_at:1}}).label,'Refresh progress');
assert.equal(model.hubJob({exit:0,progress:{...liveProgress,active:false}}).label,'Progress ended');
assert.equal(model.hubJob({exit:0,progress:{...liveProgress,phase:'completed'}}).label,'Succeeded');
for(const value of ['javascript:alert(1)','file:///private/secret','data:text/html,hello','not-a-url'])assert.equal(model.safeURL(value),null);
assert.equal(model.safeURL('https://example.com/check'),'https://example.com/check');
const observed={machine:{connected:true},generated_at:new Date(Date.now()-120000).toISOString(),_status:{duration_s:7,budget_s:45}};
const failed=model.retain(observed,{request:9,error:'failed'});
assert.equal(failed.machine.connected,true);assert.equal(failed._status.stale,true);assert.equal(failed.request,9);
assert.match(model.caption(failed),/Observed 2 min ago, refresh failed.*7.0 s/);
assert.match(model.caption({...observed,_status:{pending:true}}),/Observed 2 min ago, refreshing/);
assert.match(model.caption({_status:{pending:true,budget_s:45}}),/up to 45 seconds/);
const need=assess({needs_you:[{kind:'hypervisor',text:'unknown',why:'why',action:'action',url:'https://example.com/',verify:'verify'}]}).need[0];
assert.equal(need.why,'why');assert.equal(need.action,'action');assert.equal(need.url,'https://example.com/');assert.equal(need.verify,'verify');
assert.equal(assess({needs_you:[{kind:'host',host:'worker',text:'worker offline'}],fleet:{hosts:[{host:'worker',net:{online:false}}]}}).need.length,1);
for(const delivery of [undefined,'unknown']){const issue=model.contributionIssue({lane:'qa',delivery});for(const key of ['why','action','verify'])assert.ok(issue[key]);}
console.log('Status transparency: safe URLs, retained failures, observation age/budget, issue fields, dedupe and older-service fallbacks passed.');

for(const status of [failures,{needs_you:[{kind:'legacy',text:'Something failed'}]}, {backups:{hosts:[{host:'vm',node:'node',reachable:true,inventory_complete:true,scheduled:true,jobs:1,last_dump_age_h:null}],lanes:[lane('waiting')]}}]){
 for(const row of assess(status).need)for(const key of ['why','action','verify'])assert.ok(row[key],key);
}
const backupNeed=assess({backups:{hosts:[{host:'vm',node:'node',reachable:true,inventory_complete:true,scheduled:true,jobs:1,last_dump_age_h:null}]}}).need[0];
assert.match(backupNeed.detail,/no completed backup/i);assert.doesNotMatch(backupNeed.detail,/no backup job/);
console.log('Derived and grouped alerts carry explanations; a configured backup job is not mistaken for no job.');

// Notification delivery must never direct an owner decision outside Review.
for (const file of fs.readdirSync(path.join(__dirname,'../ui')).filter(f=>/\.(html|js)$/.test(f))) {
 const content=fs.readFileSync(path.join(__dirname,'../ui',file),'utf8');
 assert.doesNotMatch(content,/\b(?:approve|reject)\b[^"\n]*\b(?:digest buttons|on Telegram|Archive view)\b/i,`${file}: retired decision instructions`);
}
console.log('Decision guidance: no retired digest, Telegram or Archive-view approval instructions in app UI.');

const recovering={ts:new Date(Math.floor(Date.now()/1000)*1000).toISOString(),exit:1,source:'hub-runner',health:{state:'awaiting_verification',summary:'Previous blocker cleared; awaiting backup',checked_at:Date.now()/1000,verification_deadline:Date.now()/1000+3600}};
const snapshot={machine:{host:'local'},hub:{via:'local',reachable:true,jobs:{autocommit:recovering}},jobs:[{label:'com.sovereign.hub.autocommit',last_exit:1,last_run:Date.parse(recovering.ts)/1000}],needs_you:[{kind:'job',text:'com.sovereign.hub.autocommit last exited 1. Check its log.'}]};
assert.equal(assess(snapshot).need.length,0);assert.equal(assess(snapshot).waiting.length,1);
assert.equal(assess({...snapshot,_status:{stale:true}}).need.length,1);
assert.equal(assess({hub:{jobs:{autocommit:{...recovering,health:{...recovering.health,verification_deadline:1}}}}}).need.length,1);
assert.equal(assess({hub:{jobs:{autocommit:{...recovering,exit:0}}}}).waiting.length,0);
assert.equal(assess({hub:{jobs:{autocommit:{...recovering,health:{state:'needs_attention'}}}}}).need.length,1);
for(const via of ['ssh hub',undefined])for(const exit of [0,1]){
 const separate=assess({...snapshot,hub:{via,reachable:true,jobs:{autocommit:{...recovering,exit}}}});
 // One failure is one row: the service's own row, which lands on the job.
 assert.equal(separate.need.filter(n=>n.jump?.id==='com.sovereign.hub.autocommit').length,1);
 assert.ok(separate.need.some(n=>n.need===0&&n.state==='down'));
 assert.equal(separate.waiting.length,exit===1?1:0);
}
assert.ok(assess({...snapshot,hub:{...snapshot.hub,jobs:{autocommit:{...recovering,exit:0}}}}).need.length>0);
assert.ok(assess({...snapshot,jobs:[{label:'com.sovereign.hub.autocommit-old',last_exit:1}],needs_you:[{kind:'job',text:'com.sovereign.hub.autocommit-old last exited 1.'}]}).need.length>0);
assert.ok(assess({...snapshot,needs_you:[{kind:'job',host:'other',text:snapshot.needs_you[0].text}]}).need.length>0);
for(const last_run of [undefined,NaN,Date.parse(recovering.ts)/1000+1,Date.parse(recovering.ts)/1000-1]){
 assert.ok(assess({...snapshot,jobs:[{...snapshot.jobs[0],last_run}]}).need.some(n=>n.jump?.id==='com.sovereign.hub.autocommit'));
}
console.log('Alert lifecycle: verified blocker, stale observations, missed verification, deduplicated local jobs, successful recovery and new failures passed.');

// A job that stood down on purpose is a condition to clear, not a failure to fix. The
// curate tick exits 75 while the review queue is full: curation is paused for every
// lane, nothing is broken, and the owner clears it by deciding.
const pausedJob={ts:new Date().toISOString(),exit:75,source:'hub-runner',cadence_s:7200,
 health:{state:'paused',summary:'Review queue full, curation paused',why:'50 pending >= limit 50',
         action:'Open Sovereign → Review to compare and decide (or curator-approve on the hub).'}};
const pausedView=assess({machine:{host:'local'},hub:{via:'local',reachable:true,jobs:{curate:pausedJob}}});
assert.equal(pausedView.need.filter(n=>n.jump?.id==='hub:job:curate').length,0,'a paused job is not a failure');
const pausedRow=pausedView.waiting.find(w=>w.jump?.id==='hub:job:curate');
assert.ok(pausedRow,'a paused job waits on the owner');
assert.equal(pausedRow.detail,'Review queue full, curation paused');
assert.equal(box.window.SovStatus.hubJob(pausedJob).label,'Paused');
assert.equal(box.window.SovStatus.hubJob({...pausedJob,health:{}}).label,'Needs attention','an unnamed non-zero exit is still a failure');
console.log('A paused hub job reads as a named condition waiting on the owner, never as a failed run.');

// "this copy is behind the hub" must compare the SAME lane in two places. It used to
// subtract a hub lane's age from a remote host's harness run age, so a mirror that had
// not run in sixteen days elsewhere was reported here as this copy being sixteen days
// stale. Done properly it catches the sync failing to carry a file type.
const copyRow = d => assess(d).stale.find(x => x.name === 'this copy');
// A dead mirror on another host is NOT this copy falling behind.
assert.equal(copyRow({machine:{host:'here'},hub:{lanes:{alpha:{age_h:0.1}}},
  fleet:{hosts:[{host:'elsewhere',harnesses:[{harness:'some-tool',lane:'alpha',run_age_h:393.9}]}]},
  lanes:[{lane:'alpha',vault_age_h:0.1,hub_age_h:0.1}]}), undefined);
// A lane whose content is older here than on the hub IS, and the row names that lane.
const behind = copyRow({machine:{host:'here'},hub:{lanes:{}},obsidian:{sync:'a sync'},
  lanes:[{lane:'beta',vault_age_h:373.2,hub_age_h:348.0},{lane:'alpha',vault_age_h:0.1,hub_age_h:0.1}]});
assert.ok(behind, 'a real lag must be reported');
assert.match(behind.detail, /beta/);
assert.match(behind.detail, /has not carried everything/);
assert.ok(behind.age_h > 25 && behind.age_h < 26, 'reports the actual gap, not a harness run age');
// The curator's own lane is exempt: the law makes its operational state hub-authoritative.
assert.equal(copyRow({machine:{host:'here'},hub:{lane:'curator',lanes:{}},
  lanes:[{lane:'curator',vault_age_h:12.7,hub_age_h:0.1}]}), undefined);
// A retired lane never raises it either.
assert.equal(copyRow({machine:{host:'here'},hub:{lanes:{}},
  lanes:[{lane:'old',vault_age_h:900,hub_age_h:1,retired:true}]}), undefined);
console.log('Copy lag: compares one lane in two places, names it, exempts the curator lane and retired lanes.');

// The app must say whether it was built from the source on this machine. Nothing did,
// which is how one machine ran a 0.1 prototype for months while the other moved through
// twenty-two builds and every release note truthfully called the first "unchanged".
const APP_ROWS = ['Update available','Up to date','Update status unknown'];
const appRow = d => { const a = assess(d); return [...a.need, ...a.stale, ...a.fresh].find(x => APP_ROWS.includes(x.name)); };
const withApp = (app, rev) => ({machine:{host:'here',app,template_rev:rev}});
// Built from what is here: a quiet confirmation, not an alert.
const current = appRow(withApp({installed:true,version:'1.2.3',build:'9',source_commit:'abc1234'},'abc1234 2026-01-01'));
assert.equal(current.state,'live'); assert.equal(current.name,'Up to date');
assert.match(current.detail,/newest build of this device's source/);
assert.match(current.why,/abc1234/,'the revision is evidence, so it belongs in the drawer');
assert.ok(!/abc1234/.test(current.detail),'the headline must not lead with a commit hash');
// Built from something else: a thing to do.
const appBehind = appRow(withApp({installed:true,version:'1.0.0',build:'1',source_commit:'old9999'},'abc1234 2026-01-01'));
assert.equal(appBehind.state,'warn'); assert.equal(appBehind.cause,'app-behind');
assert.equal(appBehind.name,'Update available');
assert.match(appBehind.detail,/newer version of Sovereign is ready to install/);
assert.equal(appBehind.action,'Update now');
assert.equal(appBehind.actionKind,'app-update');
// The hashes are evidence; a person reading the row should not have to decode them.
assert.ok(!/old9999|abc1234/.test(appBehind.detail),'no commit hashes in the headline');
assert.match(appBehind.why,/old9999/); assert.match(appBehind.why,/abc1234/);
assert.ok(assess(withApp({installed:true,version:'1.0.0',build:'1',source_commit:'old9999'},'abc1234 2026-01-01')).need.some(x=>x.name==='Update available'),'behind belongs in needs');
// Unequal is not newer: a build from a worktree or a later branch than this checkout is
// not behind it, and Update would install the older source. Say so, offer nothing.
const ahead = assess(withApp({installed:true,version:'0.6.0',build:'39',source_commit:'new8888',behind:false},'abc1234 2026-01-01'));
assert.ok(![...ahead.need,...ahead.stale,...ahead.fresh].some(x=>x.name==='Update available'),'an older source is never offered as an update');
const differs = ahead.stale.find(x=>x.cause==='app-ahead');
assert.equal(differs.name,'Source differs'); assert.equal(differs.actionKind,undefined);
assert.match(differs.action,/source/); assert.ok(!/Jobs|log/.test(differs.action),'no generic job guidance');
assert.match(differs.detail,/nothing newer to install/); assert.match(differs.why,/new8888/);
assert.equal(model.brief(differs),'nothing newer');
assert.equal(appRow(withApp({installed:true,version:'1.0.0',build:'1',source_commit:'old9999',behind:true},'abc1234 2026-01-01')).name,'Update available');
// A local build is still current when its commit matches.
assert.equal(appRow(withApp({installed:true,version:'1.2.3',build:'9',source_commit:'abc1234+local'},'abc1234 2026-01-01')).state,'live');
// An unstamped build says so rather than implying an agreement it cannot check.
const unstamped = appRow(withApp({installed:true,version:'0.1',build:'1',source_commit:null},'abc1234 2026-01-01'));
assert.equal(unstamped.cause,'app-unstamped'); assert.equal(unstamped.name,'Update status unknown');
assert.equal(unstamped.action,'Update now'); assert.equal(unstamped.actionKind,'app-update');
// No app installed raises nothing at all.
assert.equal(appRow(withApp({installed:false},'abc1234 2026-01-01')), undefined);
console.log('App currency: current, behind, local build, unstamped and absent all reported honestly.');

// A lane's contract is what grants its permissions. Nothing compared contract with
// reality until 2026-09-20, which is how a read wire nobody intended, a mirror gate no
// contract declared, and a lane the law never named all ran unnoticed.
const permRows = d => assess(d).stale.filter(x => x.cause === 'permission-drift');
const lanes = fs => ({machine:{host:'here'},lanes:fs});
assert.equal(permRows(lanes([{lane:'clean',findings:[]}])).length, 0);
const drift = permRows(lanes([{lane:'alpha',relative_path:'raw/workspaces/alpha',
  findings:[{level:'warn',text:'git-branch lane declares no mirror_harnesses'}]}]));
assert.equal(drift.length,1);
assert.equal(drift[0].name,'lane alpha');
assert.match(drift[0].detail,/mirror_harnesses/);
assert.match(drift[0].action,/raw\/workspaces\/alpha\/LANE\.md/);
assert.equal(drift[0].causeLabel,'have a permission their contract does not settle');
// info-level notes (a retired lane saying so) are not drift and must not raise a row.
assert.equal(permRows(lanes([{lane:'old',findings:[{level:'info',text:'retired'}]}])).length, 0);
// Several lanes each contribute their own row, so grouping can count them.
assert.equal(permRows(lanes([{lane:'a',findings:[{level:'warn',text:'x'}]},
                             {lane:'b',findings:[{level:'warn',text:'y'},{level:'info',text:'z'}]}])).length, 2);
console.log('Permission drift: contract-vs-reality findings surface per lane, info notes do not.');

// What is waiting for the curator. The hub always reported its queue depth and the app
// showed none of it: "open Review" while thousands of items sat unjudged. The rate is
// what makes the number mean anything to a person.
// The reading queue is work the system does by itself: its own list, never 'waiting', which
// holds runs awaiting verification and feeds the Glance and the crown's verdict.
const queueRows = d => { const a = assess(d); assert.equal(a.waiting.filter(x => (x.cause||'').startsWith('queue-')).length, 0); return a.queue; };
const hubQueue = (status) => ({machine:{host:'here'},hub:{reachable:true,status}});
const q = queueRows(hubQueue({judged:50,deferred:2451,coverage:{processable:6740,judged_ever:3812,unjudged_in_window:2259,stranded_pre_watermark:669}}));
assert.equal(q.length,2);
const w = q.find(x=>x.cause==='queue-waiting');
assert.match(w.detail,/2,259 items/); assert.match(w.detail,/46 nights at 50 a night/);
assert.match(w.why,/6,740/); assert.match(w.why,/3,812/); assert.match(w.why,/2,451/);
// Nothing is lost while it waits, and the row says so rather than reading as an alarm.
assert.match(w.action,/Nothing is lost/);
const s = q.find(x=>x.cause==='queue-stranded');
assert.match(s.detail,/669 items/); assert.match(s.detail,/will not be reached by the nightly/);
// An empty queue says nothing at all.
assert.equal(queueRows(hubQueue({judged:50,coverage:{unjudged_in_window:0,stranded_pre_watermark:0}})).length,0);
// A run that judged nothing must not divide by zero or invent a rate.
const noRate = queueRows(hubQueue({judged:0,coverage:{unjudged_in_window:12}}))[0];
assert.match(noRate.detail,/12 items/); assert.ok(!/night/.test(noRate.detail),'no rate claimed when none is known');
console.log('Queue depth: waiting and stranded are named with the rate that makes them mean something.');

// How complete the archive is, always visible. One headline figure only: the share of
// eligible material the curator has actually read. A single blended "score" would hide
// which kind of incomplete you are looking at.
const comp = d => assess(d).completeness;
const full = comp({machine:{host:'here'},hub:{reachable:true,pending:2,status:{coverage:{processable:6740,judged_ever:3812,unjudged_in_window:2259,stranded_pre_watermark:669}}},
  lanes:[{lane:'a',vault_age_h:1},{lane:'b',vault_age_h:2},{lane:'c',vault_age_h:900},{lane:'old',vault_age_h:1,retired:true}]});
assert.equal(full.read.pct,57); assert.equal(full.read.judged,3812); assert.equal(full.read.total,6740);
assert.equal(full.waiting,2259); assert.equal(full.out_of_reach,669);
// A retired lane is not a producer that stopped delivering.
assert.equal(full.producers.delivering,2); assert.equal(full.producers.total,3);
assert.equal(full.gate,2);
assert.match(full.headline,/57% read/); assert.match(full.headline,/2 of 3 producers/); assert.match(full.headline,/2 waiting on you/);
assert.match(full.detail,/3,812 of 6,740/);
// Nothing waiting is said plainly, not left blank for the reader to interpret.
assert.match(comp({machine:{host:'here'},hub:{reachable:true,pending:0,status:{coverage:{processable:10,judged_ever:5}}},lanes:[]}).headline,/nothing waiting on you/);
// Before the curator has reported, claim no percentage at all.
const unknown = comp({machine:{host:'here'},hub:{reachable:true,status:{}},lanes:[]});
assert.equal(unknown.read.pct,null);
assert.match(unknown.detail,/has not reported/);
assert.ok(!/%/.test(unknown.headline),'no percentage invented from no data');
console.log('Completeness: one honest share read, producers and gate beside it, nothing invented.');

// Home must carry captured output for each grouped job and escape hostile log text.
const output='<img src=x onerror=alert(1)>';
const group=assess({hub:{jobs:{kit:{exit:65,health:{failure_output:output}},autocommit:{exit:1,health:{failure_output:'push failed'}}}}}).need.find(r=>r.group==='job-failed');
assert.equal(group.members[0].failure_output,output);
assert.equal(group.members[1].failure_output,'push failed');
// Today renders these as text nodes, so hostile log text stays text; tests/home.js and the
// job-output scene check that in the real DOM. Here the data must simply arrive intact.
const local=assess({needs_you:[{kind:'job',why:'Recent error',failure_output:'capture failed'}]}).need[0];
assert.equal(local.failure_output,'capture failed');
console.log('Captured job output survives grouped and local alerts.');

// A row's reason is two or three words; the sentence stays in its detail.
assert.equal(model.brief(group),'failed');
assert.equal(model.brief({cause:'need:gate'}),'waiting');
assert.equal(model.brief({cause:'unreachable'}),'unreachable');
assert.equal(model.brief({cause:'need:host'}),'unreachable');
assert.equal(model.brief({cause:'mirror-late',age_h:240}),'silent 10d');
assert.equal(model.brief({cause:'mirror-late',age_h:null}),'late');
assert.equal(model.brief({cause:'no-backup'}),'no backup');
assert.equal(model.brief({cause:'need:job',detail:'runner: last run exited 0; error output was recorded'}),'errors logged');
assert.equal(model.brief({cause:'need:job',detail:'runner last exited 1'}),'failed');
assert.equal(model.brief({detail:'pushed, awaiting hub acceptance'}),'awaiting hub');
assert.equal(model.brief({cause:'something-new',detail:'A whole sentence.'}),'');
assert.equal(model.seen({}),'checking…');
assert.equal(model.seen({machine:{},_status:{pending:true}}),'checking…');
assert.equal(model.seen({machine:{},_status:{error:'probe failed'}}),'refresh failed');
assert.match(model.seen({machine:{},generated_at:new Date().toISOString()}),/\d/);
console.log('Short reasons and observed time: known causes have a short form, unknown ones fall back to their sentence.');

// The crown's verdict comes from the same assessment wherever the window is, Today included.
const verdict=d=>model.verdict(d,{getItem(){return null},setItem(){}});
const connected={machine:{host:'here',connected:true},generated_at:new Date().toISOString()};
for(const [d,text] of [[{...connected,_status:{error:'probe failed'}},'probe failed'],[{error:'no status'},'no status']]){const v=verdict(d);assert.equal(v.state,'down');assert.equal(v.text,text);}
assert.equal(verdict({...connected,_status:{pending:true}}).state,'warn');
assert.equal(verdict({machine:{connected:false}}).state,'idle','a local-only archive is not all good, it is not connected');
assert.equal(verdict({...connected,jobs:[{label:'job-a',last_exit:1}]}).state,'down');
assert.match(verdict({...connected,jobs:[{label:'job-a',last_exit:1}]}).text,/^Attention: job-a failed/);
assert.equal(verdict({...connected,backups:{lanes:[{lane:'producer',delivery:'waiting'}]}}).state,'warn');
assert.equal(verdict(connected).state,'live');
console.log('Verdict: one sentence and the worst state from the shared assessment.');
const backlog={...connected,hub:{reachable:true,status:{coverage:{unjudged_in_window:750,stranded_pre_watermark:2037}}}};
assert.equal(verdict(backlog).state,'live','a reading queue is not awaiting verification');
assert.equal(verdict({...backlog,harnesses:[{id:'tool',name:'tool',state:'connected',cadence_s:3600,run_age_h:1.5}]}).state,'warn','a backlog never hides a stale source');
console.log('Verdict: the reading queue neither greys the crown nor hides staleness.');
// Cards carry age_d, days since created on the service's own calendar, never created itself.
const cards={...connected,archive:{cards:[{slug:'a',age_d:0},{slug:'b',age_d:0},{slug:'c',age_d:5},{slug:'d',age_d:null}]}};
assert.equal(assess(cards).fresh.find(f=>f.name==='archive')?.detail,'2 cards landed today');
assert.equal(verdict(cards).text,'All good. 2 cards landed today.');
assert.equal(verdict({...connected,archive:{cards:[{age_d:3}]},hub:{status:{judged:50,new_proposals:1}}}).text,'All good. The judge kept 1 of 50 last run.');
console.log('Cards landed today are counted from their age, in the Glance verdict too.');
// A local job the service reports is one row: red, named by its job, first, landing on it.
const runnerLabel='com.sovereign.connector.runner';
for(const row of [{kind:'job',text:runnerLabel+' last exited 1. Check /tmp/runner.error.log.'},{kind:'xcode-license',text:runnerLabel+' cannot start: its program is /usr/bin/python3, an Xcode shim.'}]){
 const one=assess({machine:{host:'here'},jobs:[{label:runnerLabel,last_exit:row.kind==='job'?1:69}],needs_you:[{kind:'gate',text:'2 waiting'},row]}).need;
 assert.equal(one.length,2,row.kind+': one row for one failure');
 assert.equal(one[0].name,'runner');assert.equal(one[0].state,'down');assert.equal(one[0].jump.view,'jobs');assert.equal(one[0].jump.id,runnerLabel);
}
// A job with only recent error output, or one that exited 0, stays amber.
assert.equal(assess({machine:{host:'here'},needs_you:[{kind:'job',text:'Capture last exited 0; recent error output remains.'}]}).need[0].state,'warn');
assert.equal(assess({machine:{host:'here'},jobs:[{label:runnerLabel,last_exit:0}],needs_you:[{kind:'job',text:runnerLabel+': last run exited 0; error output was recorded within the last day.'}]}).need[0].state,'warn');
console.log('A failed local job is one row, named by its job, red and first.');
// A refused client intake is one row, named by its client, and gone with its device.
const refusedClient={machine:{host:'here',vault:'/a',connected:true},clients:[{client_id:'field-laptop',state:'rejected',reason:'git_fetch_failed'},{client_id:'desk',state:'imported'}],
 needs_you:[{kind:'client-intake',text:'Client intake needs attention: field-laptop',why:'w',action:'a',verify:'v'}]};
const intake=assess(refusedClient).need;
assert.equal(intake.length,1,'one refused client, one row');
assert.equal(intake[0].name,'field-laptop');assert.equal(intake[0].state,'down');assert.equal(model.brief(intake[0]),'intake failed');
assert.match(intake[0].detail,/git_fetch_failed/);
assert.equal(assess({...refusedClient,clients:undefined,hub:{clients:refusedClient.clients}}).need.length,1,'the hub list serves an older status');
const disassociated=model.associations({...refusedClient,device_associations:{available:true,scope:'/a',disassociated:['field-laptop']}});
assert.equal(assess(disassociated).need.length,0,'a disassociated client raises nothing');
console.log('A refused client intake is one row, and disassociation hides it.');
// A service row is named, coloured and sent where its own next step points, by its kind.
const kinds=assess({machine:{host:'here',hub_pointer:'hubhost:/archive'},hub:{reachable:false,hub_host:'Hub-Machine-Name'},harnesses:[{id:'cursor-here',name:'Cursor'}],needs_you:[
 {kind:'host',host:'vm-a',text:'This device cannot currently reach vm-a.'},
 {kind:'hub',text:'The hub did not answer (ssh hubhost). Governance state is unknown until it does.'},
 {kind:'hypervisor',node:'node-a',text:'Backup posture of 3 VMs on node-a is unknown.'},
 {kind:'relay',text:"The mover's source /x is gone."},
 {kind:'runner-stalled',text:'The connector job has not finished a tick since then.'},
 {kind:'runner-standing-down',text:'The connector job has stood down 3 tick(s) in a row.'},
 {kind:'lane-silent',harness:'cursor-here',text:'Cursor: the connector job is running but has not visited this lane.'},
 {kind:'gate',text:'2 proposals waiting.'}]}).need;
const byKind=k=>kinds.find(n=>n.cause==='need:'+k);
assert.equal(byKind('host').state,'down','an unreachable device is red wherever it is reported');
assert.equal(byKind('hub').name,'Hub');assert.equal(byKind('hub').state,'down');assert.equal(byKind('hub').jump.view,'hosts');assert.equal(byKind('hub').jump.id,'hubhost');
assert.equal(model.brief(byKind('hub')),'unreachable');
assert.equal(byKind('hypervisor').name,'node-a');assert.equal(byKind('hypervisor').jump.view,'backups');assert.equal(model.brief(byKind('hypervisor')),'backup unknown');
assert.equal(byKind('relay').jump.view,'backups');
assert.equal(byKind('runner-stalled').name,'runner');assert.equal(byKind('runner-stalled').state,'down');assert.equal(byKind('runner-stalled').jump.view,'jobs');
assert.equal(byKind('runner-standing-down').jump.view,'jobs');assert.equal(model.brief(byKind('runner-standing-down')),'standing down');
assert.equal(byKind('lane-silent').name,'Cursor');assert.equal(byKind('lane-silent').jump.view,'tools');assert.equal(byKind('lane-silent').jump.id,'cursor-here');
const firstAmber=kinds.findIndex(n=>n.state!=='down'),lastRed=kinds.map(n=>n.state).lastIndexOf('down');
assert.ok(lastRed<firstAmber,'red rows come first: '+kinds.map(n=>n.state+' '+n.name).join(', '));
assert.equal(assess({machine:{host:'here'},hub:{reachable:false,hub_host:'hubhost'}}).need[0].jump.id,'hubhost','a derived hub alert lands on the hub too');
console.log('Service rows: named, coloured and routed by kind; red rows first.');
assert.equal(verdict({...connected,needs_you:[{kind:'legacy'}]}).state,'warn','a service row without a sentence still gives a verdict');
assert.equal(verdict({...connected,needs_you:[{kind:'host',host:'vm-a',text:'This device cannot currently reach vm-a.'},{kind:'host',host:'vm-b',text:'This device cannot currently reach vm-b.'}]}).text,
 'Attention: This device cannot currently reach vm-a, and 1 more.','a service sentence is said once, without its name in front');
// A group is counted in the noun of its members, and its drawer names every one of them.
const lateMirrors=assess({machine:{host:'here'},fleet:{hosts:[{host:'other',harnesses:['a','b','c','d','e','f'].map(t=>({harness:t,lane:t,run_age_h:30}))}]}}).need;
assert.equal(lateMirrors.length,1);assert.equal(lateMirrors[0].name,'6 sources','six late tools on one device are six sources');
for(const t of ['a','b','c','d','e','f'])assert.match(lateMirrors[0].detail,new RegExp(t+' on other'));
assert.equal(assess({backups:{hosts:[1,2,3].map(n=>({host:'vm-'+n,node:'node',reachable:true,inventory_complete:true,scheduled:true,last_dump_age_h:null}))}}).need[0].name,'3 devices');
assert.equal(assess({fleet:{hosts:[{host:'a',net:{online:false}},{host:'b',net:{online:false}}]}}).need[0].name,'2 devices');
assert.equal(assess({clients:[{client_id:'a',state:'rejected'},{client_id:'b',state:'error'}]}).need[0].action.startsWith('Inspect each listed item in Sources → Map.'),true);
assert.equal(result.need.find(x=>x.group==='job-failed').name,'2 jobs');
console.log('Groups: jobs, sources and devices, every member named.');
// A lane on a disassociated device is not a producer this archive is waiting on.
const assocLanes=model.associations({machine:{host:'here',vault:'/a'},device_associations:{available:true,scope:'/a',disassociated:['gone']},
 lanes:[{lane:'live',host:'here',vault_age_h:1},{lane:'quiet',host:'here',vault_age_h:100},{lane:'away',host:'gone',vault_age_h:200},{lane:'away-fresh',host:'gone',vault_age_h:1}]});
const producers=assess(assocLanes).completeness.producers;
assert.equal(producers.total,2);assert.equal(producers.delivering,1);
console.log('Completeness: lanes on disassociated devices are not counted.');
// An archive the status service could not read is the worst thing on Today: red, named,
// two words, and landing on Library, which shows the error, never on Sources.
const unreadable=assess({machine:{host:'here'},needs_you:[{kind:'archive',text:'The archive could not be read: archive folder not found. It is configured at /a.'}]}).need[0];
assert.equal(unreadable.name,'Archive');assert.equal(unreadable.state,'down');assert.equal(model.brief(unreadable),'unreadable');
assert.equal(unreadable.jump.view,'archive');assert.match(unreadable.action,/Library/);
console.log('An unreadable archive is one red row that lands on Library.');
// The Sources tile counts a lane another device's mirror writes by that mirror's observable
// cadence, as Sources and Today's mirror rows do, and any other lane by the 48-hour clock.
const mirrored=assess({machine:{host:'here'},fleet:{hosts:[{host:'other',harnesses:[{harness:'tool',lane:'far',run_age_h:30}]}]},
 lanes:[{lane:'far',vault_age_h:30},{lane:'near',vault_age_h:30}]});
assert.equal(mirrored.completeness.producers.delivering,1,'a mirror past its cadence is not delivering on the tile');
assert.ok(mirrored.need.some(n=>n.cause==='mirror-late'),'while Today calls it late');
assert.equal(assess({machine:{host:'here'},fleet:{hosts:[{host:'other',harnesses:[{harness:'tool',lane:'far',run_age_h:0.5}]}]},lanes:[{lane:'far',vault_age_h:30}]}).completeness.producers.delivering,1);
console.log('Completeness: a remote mirror lane is counted at its own cadence, as Sources reads it.');
// A lane whose own contract says retired is not expected to push, whatever its last commit:
// Sources lists it under Removed, so Today must not call it late.
const retiredPush=assess(model.associations({machine:{host:'here'},lanes:[{lane:'old',status:'retired 2026-09-01'}],
 backups:{lanes:[{lane:'old',delivery:'accepted',pushed:'2000-01-01T00:00:00Z'}]}}));
assert.equal([...retiredPush.need,...retiredPush.stale].filter(x=>/old/.test(x.name)).length,0,'a retired lane raises no push alarm');
console.log('Producer pushes: a lane retired by its contract raises nothing.');
// A paused job waits on the owner; it is not a run awaiting verification, and it never
// hides a stale snapshot from the crown.
const pausedHub=(extra={})=>({...connected,hub:{reachable:true,jobs:{burndown:{ts:new Date().toISOString(),exit:75,health:{state:'paused',summary:'Stood down'}}}},...extra});
const onlyPaused=verdict(pausedHub());
assert.equal(onlyPaused.state,'idle');assert.match(onlyPaused.text,/^burndown paused until you act/);assert.ok(!/verification/.test(onlyPaused.text),onlyPaused.text);
const pausedStale=verdict(pausedHub({backups:{snapshots:{newest_age_h:30}}}));
assert.equal(pausedStale.state,'warn','a paused job never hides staleness');assert.match(pausedStale.text,/^Stale: daily snapshot/);
console.log('Verdict: a paused job is named as paused and never hides a stale item.');

// Today and the Glance take their headline from one function: attention items, never proposals.
{ const H=box.window.SovStatus.headline;
  assert.deepEqual({...H({machine:{connected:false}},{need:[]})},{state:'',text:'Not connected'});
  assert.deepEqual({...H({machine:{connected:true}},{need:[]})},{state:'live',text:'All clear'});
  assert.deepEqual({...H({machine:{connected:true}},{need:[{state:'warn'}]})},{state:'warn',text:'1 thing needs you'});
  assert.deepEqual({...H({machine:{connected:true}},{need:[{state:'warn'},{state:'down'}]})},{state:'down',text:'2 things need you'});
  console.log('Headline: one function words Today and the Glance.'); }
