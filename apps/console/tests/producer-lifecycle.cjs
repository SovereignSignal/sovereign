const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const box={window:{},URL};vm.createContext(box);
for(const name of ['status-model.js','system-model.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui',name),'utf8'),box);
const model=box.window.SovStatus,fixture={machine:{host:'desk',vault:'/owned'},hub:{reachable:true,via:'local',pending:0},
 harnesses:[{id:'windsurf',lane:'windsurf-desk',name:'Windsurf',state:'removed',read:'instruction',job_loaded:false,hook_registered:false}],
 lanes:[{lane:'windsurf-desk',host:'desk',read:'instruction',write:'mirror',vault_age_h:1000}],
 fleet:{hosts:[{host:'desk',net:{online:true},lanes:[{lane:'windsurf-desk'}],harnesses:[{lane:'windsurf-desk',harness:'Windsurf',run_age_h:1000}]}]},
 backups:{lanes:[{lane:'windsurf-desk',delivery:'waiting'}]}};
const original=JSON.stringify(fixture),out=model.associations(fixture);
assert.equal(JSON.stringify(fixture),original);assert.equal(out.lanes.length,1);assert(out.lanes[0].retired);assert.equal(out.lanes[0].associated,false);
assert.equal(out.fleet.hosts[0].harnesses.length,0);assert.equal(out.backups.lanes.length,0);
const assessment=model.assess(out);assert(![...assessment.need,...assessment.stale].some(x=>/windsurf/i.test(x.name)));
const graph=box.window.SovEnvironment.build({root:'/owned',status:out});assert(!graph.tools.some(t=>t.name==='Windsurf'));assert(!graph.nodes.some(n=>n.id==='lane:windsurf-desk'));
const reconnected=model.associations({...fixture,harnesses:[{...fixture.harnesses[0],state:'connected',job_loaded:true,hook_registered:true}]});
assert.equal(reconnected.fleet.hosts[0].harnesses.length,1);assert.equal(reconnected.lanes[0].retired,undefined);
console.log('Retired producer: history retained, alarms and active routes removed, reconnect restored.');
