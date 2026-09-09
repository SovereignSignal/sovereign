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

const queueStatus={machine:{connected:true,vault:'/fixture'},hub:{reachable:true,pending:1,proposals:[{slug:'example'}]}};
assert.equal(g.queue(queueStatus,'/fixture').available,true);
assert.equal(g.queue(queueStatus,'/fixture').count,1);
for(const [label,data,root,known,state] of [
 ['loading',null,'/fixture',false,'loading'],['no archive',queueStatus,null,true,'no_archive'],
 ['no status',null,'/fixture',true,'loading'],['error',{error:'failed'},'/fixture',true,'unavailable'],
 ['disconnected',{machine:{connected:false}},'/fixture',true,'not_connected'],
 ['other archive',queueStatus,'/other',true,'different_archive'],
 ['offline',{...queueStatus,hub:{...queueStatus.hub,reachable:false}},'/fixture',true,'offline'],
 ['missing rows',{...queueStatus,hub:{reachable:true,pending:0}},'/fixture',true,'incomplete'],
 ['rows not loaded',{...queueStatus,hub:{reachable:true,pending:2,proposals:[]}},'/fixture',true,'incomplete'],
 ['duplicate',{...queueStatus,hub:{reachable:true,pending:2,proposals:[{slug:'x'},{slug:'x'}]}},'/fixture',true,'incomplete'],
 ['invalid slug',{...queueStatus,hub:{reachable:true,pending:1,proposals:[{slug:'../x'}]}},'/fixture',true,'incomplete']
]){const q=g.queue(data,root,known);assert.equal(q.state,state,label);assert.equal(q.available,false,label);assert.equal(q.proposals.length,0,label);assert.equal(q.count,null,label)}
const empty=g.queue({...queueStatus,hub:{reachable:true,pending:0,proposals:[]}},'/fixture');assert.equal(empty.state,'empty');assert.equal(empty.count,0);
const partial=g.queue({...queueStatus,hub:{...queueStatus.hub,pending:90}},'/fixture');assert.equal(partial.available,true);assert.match(partial.message,/Showing 1 of 90/);
console.log('Review scope and evidence: missing, offline, different archive, malformed, empty and capped queues passed.');
