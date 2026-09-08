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
