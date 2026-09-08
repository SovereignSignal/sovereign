const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const box = {window:{}}; vm.createContext(box);
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
