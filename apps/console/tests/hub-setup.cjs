const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
// The real module with a stub host and bridge. Clicks reach its document listener as they would in the page.
const listeners={},sent=[];
const host={isConnected:true,className:'',innerHTML:'',querySelector(s){return this.innerHTML.includes(s.replace(/^#/,'id="').replace(/^\.(.*)$/,'class="$1')) ? {} : null}};
const context=vm.createContext({window:{webkit:{messageHandlers:{sov:{postMessage:o=>sent.push(o)}}}},
  document:{addEventListener(k,f){listeners[k]=f},querySelector:()=>null,body:{dataset:{view:'setup'}}},Date,Math,JSON,String,Object});
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

// A reply that lands after the owner has moved on stays out of the page that now holds the pane.
click('hub-preview');
req=sent.filter(m=>m.cmd==='hubOperation').pop();
context.document.body.dataset.view='settings';host.innerHTML='<div class="set-pane">Settings</div>';
hub.deliver('hubResult',{request:req.request,applied:false,exit:0,job:'nightly'});
assert.equal(host.innerHTML,'<div class="set-pane">Settings</div>');
// The Backups pane shares the form styling; it is not the Hub form, so coming back draws Hub setup.
host.innerHTML='<section class="hub-form archive-backups" aria-label="Archive backups"></section>';
context.document.body.dataset.view='setup';hub.mount(host,'/archive');
assert.match(host.innerHTML,/id="hub-operation"/);
assert.match(status(),/Review the exact changes/,'coming back shows the reply that arrived meanwhile');
console.log('Hub setup: a late reply never paints over another view, and Backups is not mistaken for it.');

// A preview or check never holds navigation or quit; only an apply does.
click('hub-preview');
assert.equal(hub.busy,false,'a preview does not hold the owner');
hub.deliver('hubResult',{request:sent.filter(m=>m.cmd==='hubOperation').pop().request,applied:false,exit:0,job:'nightly'});
click('hub-apply');
assert.equal(hub.busy,true,'an apply holds the owner');
hub.deliver('hubResult',{request:sent.filter(m=>m.cmd==='hubOperation').pop().request,applied:true,exit:0,job:'nightly'});
assert.equal(hub.busy,false);

// A preview for one archive that answers after another was opened cannot be applied to it.
click('hub-preview');
req=sent.filter(m=>m.cmd==='hubOperation').pop();
hub.mount(host,'/other');
hub.deliver('hubResult',{request:req.request,applied:false,exit:0,job:'nightly'});
assert.doesNotMatch(status(),/Review the exact changes/);
assert.match(host.innerHTML,/id="hub-apply" disabled/);
console.log('Hub setup: only an apply holds navigation, and a preview for another archive is dropped.');

