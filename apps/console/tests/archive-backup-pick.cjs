const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// Choose… asks the native picker for a path. Restore needs an existing recovery key, so the
// request must say which action it serves; Save destination may name a new key.
const listeners={},posted=[];
const context=vm.createContext({window:{webkit:{messageHandlers:{sov:{postMessage:o=>posted.push(o)}}}},
  document:{addEventListener(kind,f){listeners[kind]=f},querySelector(){return null}},Date,Number});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/archive-backups.js'),'utf8'),context);
const click=dataset=>listeners.click({target:{closest:()=>({id:'',dataset})}});
for(const action of ['restore','configure']){
  click({abAction:action});click({abPick:'key'});
  const pick=posted.at(-1);
  assert.equal(pick.cmd,'archiveBackupPick');assert.equal(pick.field,'key');assert.equal(pick.action,action);
}
console.log('Archive backup pick: the native picker is told whether a key must already exist.');
