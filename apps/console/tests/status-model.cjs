const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const box = {window:{},URL}; vm.createContext(box);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/status-model.js'),'utf8'),box);
const assess = box.window.SovStatus.assess;
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

for(const status of [failures,{needs_you:[{kind:'legacy',text:'Something failed'}]}, {backups:{hosts:[{host:'vm',node:'node',reachable:true,jobs:1,last_dump_age_h:null}],lanes:[lane('waiting')]}}]){
 for(const row of assess(status).need)for(const key of ['why','action','verify'])assert.ok(row[key],key);
}
const backupNeed=assess({backups:{hosts:[{host:'vm',node:'node',reachable:true,jobs:1,last_dump_age_h:null}]}}).need[0];
assert.match(backupNeed.detail,/no completed backup/);assert.doesNotMatch(backupNeed.detail,/no backup job/);
console.log('Derived and grouped alerts carry explanations; a configured backup job is not mistaken for no job.');

// Notification delivery must never direct an owner decision outside Review.
for (const file of fs.readdirSync(path.join(__dirname,'../ui')).filter(f=>/\.(html|js)$/.test(f))) {
 const content=fs.readFileSync(path.join(__dirname,'../ui',file),'utf8');
 assert.doesNotMatch(content,/\b(?:approve|reject)\b[^"\n]*\b(?:digest buttons|on Telegram|Archive view)\b/i,`${file}: retired decision instructions`);
}
console.log('Decision guidance: no retired digest, Telegram or Archive-view approval instructions in app UI.');
