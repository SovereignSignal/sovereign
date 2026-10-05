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
{
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
// A failed check is not kept as the answer: the next refresh asks the archive host again,
// one check at a time.
const other=pane();
backups.mount(other,'/down');
const first=posts.at(-1);assert.equal(first.root,'/down');
backups.deliver('archiveBackupResult',{request:first.request,error:'The archive host is unavailable.'});
assert.match(other.html,/role="alert"/);
backups.mount(other,'/down');
assert.equal(posts.at(-1).action,'status');assert.notEqual(posts.at(-1).request,first.request,'a refresh after a failure checks again');
const count=posts.length;backups.mount(other,'/down');
assert.equal(posts.length,count,'never two checks at once');
backups.deliver('archiveBackupResult',{request:posts.at(-1).request,protocol:1,destinations:[],observed_at:3000,exit:0});
assert.doesNotMatch(other.html,/role="alert"/);
backups.mount(other,'/down');
assert.equal(posts.length,count,'a good answer is kept');
console.log('Archive backups: a refresh keeps the drawn form, and a failed check is retried.');
}

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

// Reading never holds navigation or quit; only a change on the archive host does.
click('ab-refresh');
assert.equal(last().action,'status');
assert.equal(backups.busy,false,'a status read does not hold the owner');
backups.deliver('archiveBackupResult',{request:last().request,...remote,latest_restored:true});
click('',{abAction:'backup'});click('ab-preview');
assert.equal(last().apply,false);
assert.equal(backups.busy,false,'a preview does not hold the owner');
backups.deliver('archiveBackupResult',{request:last().request,action:'backup',exit:0,token:'t',files:1,source_bytes:1,host:'Hub-A'});
click('ab-apply');
assert.equal(last().apply,true);
assert.equal(backups.busy,true,'a backup in progress holds the owner');
backups.deliver('archiveBackupResult',{request:last().request,applied:true,state:'completed',exit:0});
assert.equal(backups.busy,false);
backups.deliver('archiveBackupResult',{request:last().request,...remote});

// A read for one archive that answers after another was opened is not that archive's state.
backups.mount(host,'/archive/B');
const stale=sent.filter(m=>m.action==='status').length;
backups.mount(host,'/archive/C');
assert.equal(sent.filter(m=>m.action==='status').length,stale,'one read at a time');
backups.deliver('archiveBackupResult',{request:last().request,...remote});
assert.doesNotMatch(host.innerHTML,/Destination connected/,'B\'s reply is not shown for C');
assert.deepEqual([last().action,last().root],['status','/archive/C'],'C is asked for its own status');
console.log('Archive backups: only a change holds navigation, and a reply for another archive is dropped.');

// On a remote archive host the in-page browser is the only chooser, so it must be able to set the restore folder.
backups.deliver('archiveBackupResult',{request:last().request,...remote});
click('',{abAction:'restore'});
click('',{abPick:'destination'});
assert.deepEqual([last().action,last().folder],['browse','/Users/owner']);
backups.deliver('archiveBackupResult',{request:last().request,folder:'/Users/owner/Restores',parent:'/Users/owner',entries:[]});
assert.match(host.innerHTML,/id="ab-use-folder"/,'the destination browser offers its folder');
click('ab-use-folder');
// The restore folder must not exist yet, so the choice is a new folder inside the browsed one.
assert.match(host.innerHTML,/data-ab-field="destination" value="\/Users\/owner\/Restores\/Restored Sovereign"/);
console.log('Archive backups: a remote restore can choose its new folder in the browser.');

