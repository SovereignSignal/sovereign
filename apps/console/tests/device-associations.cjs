const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const box={window:{},URL};vm.createContext(box);
for(const name of ['status-model.js','system-model.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui',name),'utf8'),box);
const model=box.window.SovStatus;
const fixture={machine:{host:'desk',vault:'/owned',hub_pointer:'hub:/owned'},hub:{via:'ssh hub',reachable:true,pending:2,clients:[{client_id:'old',state:'imported'}]},
 fleet:{hosts:[{host:'desk'},{host:'hub'},{host:'old',net:{online:false},lanes:[{lane:'old-notes'}],harnesses:[{lane:'old-tool',run_age_h:100}]},{host:'other',net:{online:false}}]},
 lanes:[{lane:'old-notes',host:'old',write:'git-branch',vault_age_h:2},{lane:'old-tool',host:'old'},{lane:'other-notes',host:'other'}],
 needs_you:[{kind:'host',host:'old'},{kind:'contribution',lane:'old-notes'},{kind:'host',host:'other'}],
 backups:{hosts:[{host:'old',reachable:true},{host:'other',reachable:true}],lanes:[{lane:'old-notes',delivery:'waiting'},{lane:'other-notes',delivery:'waiting'}]},
 device_associations:{available:true,scope:'/owned',protected_hosts:['desk','hub'],disassociated:['old']}};
const original=JSON.stringify(fixture),out=model.associations(fixture);
assert.equal(JSON.stringify(fixture),original,'Original evidence remains untouched');
assert.deepEqual(Array.from(out.fleet.hosts,h=>h.host),['desk','hub','other']);
assert.equal(out.fleet.disassociated[0].host,'old');assert.equal(out.fleet.disassociated[0].lanes.length,1);
assert.deepEqual(Array.from(out.needs_you,n=>n.host),['other']);assert.equal(out.backups.hosts.length,1);assert.equal(out.backups.lanes.length,1);
assert.equal(out.hub.pending,2);assert.equal(out.clients.length,0);assert.equal(out.hub.clients.length,0);
assert.equal(out.lanes.length,3);assert.equal(out.lanes.find(l=>l.lane==='old-notes').associated,false);
const graph=box.window.SovEnvironment.build({root:'/owned',status:out});
assert(!graph.devices.some(d=>d.name==='old'));assert(!graph.nodes.some(n=>n.id==='lane:old-notes'));
assert(graph.devices.some(d=>d.name==='other'));
const assessed=model.assess(out);assert(!JSON.stringify(assessed).includes('old-notes'));assert(!assessed.need.some(n=>n.name==='old'));
assert(assessed.need.some(n=>n.name==='other'));
for(const config of [{...fixture.device_associations,available:false},{...fixture.device_associations,scope:'/different'}])assert.equal(model.associations({...fixture,device_associations:config}).fleet.hosts.length,4);
const protectedView=model.associations({...fixture,device_associations:{...fixture.device_associations,disassociated:['DESK','hub']}});assert.equal(protectedView.fleet.hosts.length,4);
assert.equal(model.associations(out).fleet.disassociated.length,1,'Repeated projection cannot duplicate devices');
const gone=model.associations({...fixture,fleet:{hosts:[]}});assert.equal(gone.fleet.disassociated[0].host,'old','Saved device remains restorable after discovery disappears');
const restored=model.associations({...fixture,device_associations:{...fixture.device_associations,disassociated:[]}});assert.equal(restored.fleet.hosts.length,4);
assert.equal(model.retain(fixture,fixture).fleet.hosts.length,3);
console.log('Device associations: active views, alert isolation, history, graph, scope, protected hosts, rediscovery and restoration passed.');
