const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const box={window:{}};vm.createContext(box);vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/gate-model.js'),'utf8'),box);const g=box.window.GateModel,token='a'.repeat(64);
assert.equal(g.canApprove({state:'ready',fingerprint:token},null),true);
assert.equal(g.canApprove({state:'ready',fingerprint:token},{request:'running'}),false);
assert.equal(g.canApprove({state:'ready'},null),false);
for(const state of ['checking','type_conflict','update_conflict','changed','missing','invalid','unavailable','uncertain','failed','sync_pending','busy']){assert.equal(g.canApprove({state,fingerprint:token},null),false);assert.equal(g.describe(state).length,2)}
assert.equal(g.canReject({state:'type_conflict',fingerprint:token},null),true);
assert.match(g.describe('uncertain')[1],/may have completed/);
assert.match(g.describe('sync_pending')[1],/Do not approve again/);
assert.equal(g.describe('unexpected')[0],g.describe('uncertain')[0]);
console.log('Gate presentation: readiness, pending guard, all refusal states and honest uncertainty passed.');

const status={machine:{vault:'/fixture'},hub:{reachable:true,via:'local',proposals:[{slug:'example',body:'First',age_h:1,flags:[]}]}};
const copy=()=>JSON.parse(JSON.stringify(status)),key=g.reviewKey(status,'example');
let next=copy();next.hub.proposals[0].age_h=2;assert.equal(g.reviewKey(next,'example'),key);
for(const edit of [s=>s.machine.vault='/different',s=>s.hub.via='ssh other',s=>s.hub.reachable=false,s=>s.hub.proposals[0].body='Changed',s=>s.hub.proposals[0].flags=['held'],s=>s.hub.proposals[0].update_of='other']){
 next=copy();edit(next);assert.notEqual(g.reviewKey(next,'example'),key);
}
next=copy();next.hub.proposals=[];assert.equal(g.reviewKey(next,'example'),null);
assert.equal(g.decisionTimeoutMS,120000);
console.log('Review cache: age-only reuse, content/metadata/routing invalidation and 120-second deadline passed.');

const conflict={state:'type_conflict',fingerprint:token,update:true,proposal:{type:'entity'},existing:[{type:'concept',path:'knowledge/concepts/example.md'}]};
assert.equal(g.canResolve(conflict,null),true);
assert.equal(g.canResolve(conflict,{request:'busy'}),false);
assert.equal(g.canResolve({...conflict,update:false},null),false);
assert.equal(g.canResolve({...conflict,existing:[...conflict.existing,...conflict.existing]},null),false);
assert.equal(g.canResolve({...conflict,existing:[{type:'entity',path:'knowledge/concepts/example.md'}]},null),false);
assert.equal(g.canApprove({state:'resolution_pending',fingerprint:token},null),false);
assert.equal(g.canReject({state:'resolution_pending',fingerprint:token},null),false);
console.log('Resolution eligibility and interrupted-decision guards passed.');

assert.equal(g.canResolve({...conflict,existing:[{type:'concept'}]},null),false);
