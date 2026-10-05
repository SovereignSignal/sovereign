const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// The real module with a stub host and bridge. Clicks reach its document listener as they would in the page.
const listeners={},sent=[];
const host={isConnected:true,className:'',innerHTML:'',querySelector(s){return this.innerHTML.includes(s.replace(/^#/,'id="').replace(/^\.(.*)$/,'class="$1')) ? {} : null}};
const context=vm.createContext({window:{webkit:{messageHandlers:{sov:{postMessage:o=>sent.push(o)}}}},
  document:{addEventListener(k,f){listeners[k]=f},querySelector:()=>null},Date,Math,JSON,String,Object});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/hub-setup.js'),'utf8'),context);
const hub=context.window.SovHub;
const click=id=>listeners.click({target:{closest:()=>({id,dataset:{}})}});
const status=()=>/<p role="status">([^<]*)<\/p>/.exec(host.innerHTML)[1];

hub.mount(host,'/archive');
listeners.change({target:{id:'hub-operation',value:'run',dataset:{}}});
click('hub-preview');
let req=sent.filter(m=>m.cmd==='hubOperation').pop();
hub.deliver('hubResult',{request:req.request,applied:false,exit:0,job:'nightly'});
click('hub-apply');
req=sent.filter(m=>m.cmd==='hubOperation').pop();
assert.equal(req.apply,true);
// The job exited 3; native keeps the job's own exit beside the wrapper's.
hub.deliver('hubResult',{request:req.request,applied:true,exit:3,job:'nightly',log:'/h/logs/nightly-last.log'});
assert.doesNotMatch(status(),/Completed/,'a failed run is not called completed');
assert.match(status(),/Failed/);
assert.match(host.innerHTML,/exit 3/);
console.log('Hub setup: a failed job run says so with its own exit.');
