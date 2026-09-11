const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const box={window:{}};vm.createContext(box);vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/discovery-model.js'),'utf8'),box);
const m=box.window.SovDiscovery,scan={tools:[
 {id:'windsurf',name:'Windsurf',connector:'windsurf',detected:true,installed:false},
 {id:'cursor',name:'Cursor',connector:'cursor',detected:false},
 {id:'gemini-cli',name:'Gemini CLI',connector:null,detected:true,installed:true},
 {id:'notion',name:'Notion',connector:'notion',cloud:true},
 {id:'hermes',name:'Hermes agent',connector:'hermes',aliases:['Hermes desktop app'],detected:true}]};
const status={harnesses:[{id:'windsurf',state:'removed'},{id:'cursor',state:'connected'}]},before=JSON.stringify({scan,status});
const tools=m.candidates(scan,status);
assert.equal(JSON.stringify({scan,status}),before);assert.equal(tools.length,5);
assert.equal(tools[0].found,'Saved configuration found');assert.equal(tools[0].state,'Removed');
assert.equal(m.filter(tools,'','connected')[0].id,'cursor');
assert.equal(m.filter(tools,'','unsupported')[0].id,'gemini-cli');
assert.equal(m.filter(tools,'DESKTOP','available')[0].id,'hermes');
assert.equal(m.filter(tools,'absent','all').length,0);
for(const stale of [null,{error:'offline',...status},{...status,_status:{error:'timeout'}},{...status,_status:{pending:true}}]){
 const unknown=m.candidates(scan,stale);assert(unknown.every(t=>!t.harness&&!t.active));assert(!unknown.some(t=>t.state==='Connected'));
}
console.log('Discovery evidence, filters, removed producers and unavailable status passed.');
