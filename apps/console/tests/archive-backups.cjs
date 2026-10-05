const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// The real module with a stub host and bridge. Clicks reach its document listener as they would in the page.
const listeners={},sent=[];let uuid=0;
const context=vm.createContext({window:{webkit:{messageHandlers:{sov:{postMessage:o=>sent.push(o)}}}},
  document:{addEventListener(k,f){listeners[k]=f},querySelector:()=>null,body:{dataset:{view:'recovery'}}},crypto:{randomUUID:()=>'r'+(++uuid)},Date,Number,Object,String});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/archive-backups.js'),'utf8'),context);
const {protection,age}=context.window.SovBackups;
const state=d=>({observed_at:2000,destinations:d?[d]:[]});
const saved={available:true,last_success:{backup_id:'saved',finished:1000},latest_present:true,latest_restored:true,same_disk:false};
assert.equal(protection(null).op,'status');
assert.equal(protection({...state(saved),error:'offline'}).op,'status');
assert.match(protection({...state(saved),error:'offline'}).title,/fresh check/);
assert.equal(protection(state()).op,'configure');
assert.equal(protection(state({...saved,available:false})).op,'status');
assert.equal(protection(state({available:true})).op,'backup');
for(const key of ['latest_present','latest_restored']){
  assert.match(protection(state({...saved,[key]:undefined})).title,/Update/);
}
assert.match(protection(state({...saved,latest_present:false})).title,/missing or changed/);
assert.equal(protection(state({...saved,latest_restored:false})).op,'restore');
assert.equal(protection(state({...saved,same_disk:true})).op,'configure');
assert.match(protection(state(saved)).title,/passed a restore test/);
assert.match(protection(state(saved)).detail,/Changes since/);
assert.equal(age(1000,1020),'Less than a minute old');
assert.equal(age(1000,1120),'2 minutes old');
assert.equal(age(1000,11800),'3 hours old');
assert.equal(age(1000,173800),'2 days old');
assert.equal(age(2000,1000),'Age unavailable');
assert.equal(age(undefined,2000),'Age unavailable');
console.log('Archive backup protection: unavailable, unconfigured, missing, legacy, untested, same-disk, restored and age states passed.');

const backups=context.window.SovBackups;
const host={isConnected:true,className:'',innerHTML:'',querySelector(s){return this.innerHTML.includes(s.replace(/^#/,'id="').replace(/^\./,''))?{}:null}};
const last=()=>sent[sent.length-1];
const click=(id,dataset={})=>listeners.click({target:{closest:()=>({id,dataset})}});
const remote={remote:true,executor:'Hub-A',home:'/Users/owner',observed_at:2000,destinations:[{...saved,folder:'/Volumes/Disk/Backups',key:'/Users/owner/k.key',latest_restored:false}]};

// A reply that lands after the owner has moved on stays out of the page that now holds the pane.
backups.mount(host,'/archive/A');
assert.equal(last().action,'status');
context.document.body.dataset.view='settings';host.innerHTML='<div class="set-pane">Settings</div>';
backups.deliver('archiveBackupResult',{request:last().request,...remote});
assert.equal(host.innerHTML,'<div class="set-pane">Settings</div>');
context.document.body.dataset.view='recovery';backups.mount(host,'/archive/A');
assert.match(host.innerHTML,/Destination connected/,'coming back shows the reply that arrived meanwhile');
console.log('Archive backups: a late reply never paints over another view.');

