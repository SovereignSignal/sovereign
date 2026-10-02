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
 assert.ok(separate.need.some(n=>n.jump?.id==='com.sovereign.hub.autocommit'));
 assert.ok(separate.need.some(n=>n.need===0));
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
assert.match(current.detail,/newest build of this machine's source/);
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
const queueRows = d => assess(d).waiting.filter(x => (x.cause||'').startsWith('queue-'));
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
