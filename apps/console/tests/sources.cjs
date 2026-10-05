const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const box = {window:{},URL}; vm.createContext(box);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/status-model.js'),'utf8'),box);
const S = box.window.SovStatus;

// A lane whose own contract says retired is provenance, not a live source, with or
// without a removed harness elsewhere and whatever comment follows the word.
const lanes = [{lane:'old',status:'retired',vault_age_h:50},{lane:'noted',status:'retired   # 2026-10-03: moved',vault_age_h:30},
  {lane:'live',status:'onboarded',vault_age_h:1},{lane:'manifest',status:'onboarded',retired:true,vault_age_h:1}];
for (const harnesses of [[], [{id:'gone',state:'removed',lane:'gone-lane'}]]) {
  const D = S.associations({lanes:lanes.map(l=>({...l})),harnesses});
  const retired = Object.fromEntries(D.lanes.map(l=>[l.lane,!!l.retired]));
  assert.deepEqual(retired,{old:true,noted:true,live:false,manifest:true},JSON.stringify(harnesses));
  assert.deepEqual({...S.assess(D).completeness.producers},{delivering:1,total:1});
}
console.log('Sources: retired contracts and the service\'s retired flag survive the projection.');
