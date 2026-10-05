const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context=vm.createContext({window:{},document:{addEventListener(){}},Date,Number});
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
// A status refresh mounts the pane again. A drawn form is left alone, so focus, typed paths
// and open disclosures survive; after another view used the pane it is drawn again.
const posts=[];let uuid=0;
const live=vm.createContext({window:{webkit:{messageHandlers:{sov:{postMessage:m=>posts.push(m)}}}},document:{addEventListener(){},querySelector(){return null},body:{dataset:{view:'recovery'}}},crypto:{randomUUID:()=>'r'+(++uuid)},Date,Number});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/archive-backups.js'),'utf8'),live);
const backups=live.window.SovBackups;
const pane=()=>({isConnected:true,className:'',renders:0,html:'',set innerHTML(v){this.html=v;this.renders++;},get innerHTML(){return this.html;},
  get firstElementChild(){const m=/^<(\w+) class="([^"]*)"/.exec(this.html);return m?{classList:{contains:c=>m[2].split(' ').includes(c)}}:null;}});
const rows=pane();
backups.mount(rows,'/archive');
assert.deepEqual(posts.map(p=>p.action),['status']);
backups.deliver('archiveBackupResult',{request:posts[0].request,protocol:1,destinations:[],observed_at:2000,exit:0});
const drawn=rows.renders;
backups.mount(rows,'/archive');backups.mount(rows,'/archive');
assert.equal(rows.renders,drawn,'a refresh does not rebuild a drawn form');
assert.equal(posts.length,1);
rows.html='<div class="set-pane"></div>';
backups.mount(rows,'/archive');
assert.equal(rows.renders,drawn+1,'the form is drawn again after another view used the pane');
console.log('Archive backup protection: unavailable, unconfigured, missing, legacy, untested, same-disk, restored and age states, and a refresh that keeps the drawn form, passed.');
