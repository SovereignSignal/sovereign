/* Hub operations always preview; native code binds apply to the exact request. */
window.SovHub=(()=>{
  let root=null,host=null,home='',operation='install',pending=null,ready=false,result=null;
  const values={model:'',endpoint:'http://127.0.0.1:11434/v1/chat/completions',destination:'',config:'',output:'',folder:'','key-file':'',capsule:'',singleHub:false,job:'nightly'};
  const names={install:'Prepare Hub',key:'Create recovery key',recovery:'Set recovery location',snapshot:'Create recovery capsule',restore:'Restore to a new folder',status:'Inspect Hub',doctor:'Check local model',activate:'Enable schedules',run:'Run a Hub job'};
  const fields={install:['destination','model','endpoint'],key:['output'],recovery:['config','folder','key-file'],snapshot:['config','output','key-file'],restore:['capsule','destination','key-file'],status:['config'],doctor:['config'],activate:['config'],run:['config','job']};
  const labels={destination:'New destination folder',model:'Installed local model name',endpoint:'Local inference endpoint',config:'Hub configuration file',output:'New output file',folder:'Existing capsule folder','key-file':'Recovery key file',capsule:'Encrypted capsule file'};
  const explanations={install:'Prepare this Mac to maintain the open archive. Jobs stay inactive until you configure recovery and enable schedules.',key:'Create a private encryption key outside the archive. Keep a separate secure copy of it.',recovery:'Choose a capsule folder outside the archive and Hub. Keep the recovery key in a separate location.',snapshot:'Create an encrypted copy of this archive and the installed Hub tools. Existing output files are preserved.',restore:'Verify and restore a capsule into a new folder. Jobs remain inactive; open the restored archive before configuring its Hub.',activate:'Enable daily curation and snapshots, plus a weekly structural audit. A verified local model and a completed recovery capsule are required.',status:'Read the installed configuration and operation receipts.',doctor:'Check whether the configured model is available from the local inference server.',run:'Curation creates proposals for owner review. Audit reports structural problems without using a model.'};
  const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const post=o=>window.webkit.messageHandlers.sov.postMessage(o);
  function summary(p){
    if(!p||p.error)return '';
    let lines=[];
    if(p.effects)lines=p.effects;
    else if(operation==='key')lines=[p.key_file,p.note];
    else if(operation==='recovery')lines=['Capsules: '+p.config.snapshot_folder,'Key: '+p.config.recovery_key];
    else if(operation==='snapshot')lines=['Capsule: '+p.output,...p.includes.map(x=>'Includes '+x),...p.excludes.map(x=>'Excludes '+x),p.activation];
    else if(operation==='restore')lines=[p.files_verified+' files verified.','Restore location: '+p.destination,'Restored jobs stay inactive.'];
    else if(operation==='activate')lines=['Daily curation at 06:00; daily recovery at 03:00; structural audit on Fridays at 10:00.','Machine time is used. '+(p.applied?'Schedules enabled.':'Schedules will be enabled after apply.')];
    else if(operation==='doctor')lines=[p.model_available?'The configured local model is available.':'The configured local model could not be verified.'];
    else if(operation==='run')lines=[p.applied?'Job finished with exit '+p.exit+'.':'Run '+(values.job==='nightly'?'curation':'structural audit')+' for the open archive.',p.log];
    else if(operation==='status')lines=Object.entries(p.receipts||{}).map(([name,v])=>name+': '+(v.state||(v.exit==null?'completed':'exit '+v.exit)));
    return lines.length?'<ul>'+lines.filter(Boolean).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>':'';
  }
  function render(){
    if(!host?.isConnected)return;
    host.className='';
    host.innerHTML=`<div class="hub-form"><h2>Hub setup and recovery</h2><p>Archive: ${esc(root||'Open an archive first')}</p><label>Operation<select id="hub-operation" ${pending?'disabled':''}>${Object.entries(names).map(([k,n])=>`<option value="${k}" ${operation===k?'selected':''}>${n}</option>`).join('')}</select></label><p>${esc(explanations[operation])}</p><div class="fields">${fields[operation].map(f=>f==='job'?`<label>Job<select data-hub-field="job" ${pending?'disabled':''}><option value="nightly" ${values.job==='nightly'?'selected':''}>Curation</option><option value="audit" ${values.job==='audit'?'selected':''}>Structural audit</option></select></label>`:`<label>${esc(labels[f])}<input data-hub-field="${f}" value="${esc(values[f])}" ${pending?'disabled':''} autocomplete="off" spellcheck="false">${['config','key-file','capsule','folder'].includes(f)?`<button data-hub-pick="${f}" ${pending?'disabled':''}>Choose…</button>`:''}</label>`).join('')}</div>${operation==='activate'?`<label class="check"><input id="hub-single" type="checkbox" ${pending?'disabled':''} ${values.singleHub?'checked':''}>This will be the only active Hub for this archive.</label>`:''}<div class="acts"><button class="brass" id="hub-preview" ${pending||!root?'disabled':''}>${pending?'Working…':['status','doctor'].includes(operation)?'Check':'Preview'}</button><button id="hub-apply" ${!ready||pending?'disabled':''}>${esc(names[operation])}</button><button data-goto-view="jobs" ${pending?'disabled':''}>Back to Hub</button></div><p role="status">${pending?'The Hub operation is running.':result?.error?esc(result.error):result?.applied?'Completed. Review the result below.':ready?'Review the exact changes below, then apply.':''}</p>${summary(result)}${result?`<details><summary>Technical details</summary><pre aria-label="Hub operation result">${esc(JSON.stringify(result,null,2))}</pre></details>`:''}</div>`;
  }
  function request(apply){
    const data={cmd:'hubOperation',request:String(Date.now())+'-'+Math.random(),command:operation,root,apply,...Object.fromEntries(fields[operation].map(f=>[f,values[f]]))};
    if(operation==='activate')data.singleHub=values.singleHub;
    pending=data;ready=false;result=null;render();post(data);
  }
  document.addEventListener('input',e=>{if(e.target.dataset.hubField){values[e.target.dataset.hubField]=e.target.value;ready=false;const b=document.querySelector('#hub-apply');if(b)b.disabled=true;}});
  document.addEventListener('change',e=>{
    if(e.target.id==='hub-operation'){operation=e.target.value;ready=false;result=null;render();}
    if(e.target.id==='hub-single'){values.singleHub=e.target.checked;ready=false;render();}
    if(e.target.dataset.hubField){values[e.target.dataset.hubField]=e.target.value;ready=false;render();}
  });
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.id==='hub-preview'&&!pending)request(false);
    if(b.id==='hub-apply'&&ready&&!pending)request(true);
    if(b.dataset.hubPick)post({cmd:'hubPick',field:b.dataset.hubPick,directory:b.dataset.hubPick==='folder'});
  });
  return {get busy(){return !!pending;},mount(el,archive){const mounted=host===el&&root===archive&&el.querySelector('.hub-form');host=el;if(root!==archive){root=archive;ready=false;result=null;}if(!mounted)render();if(!home)post({cmd:'hubDefaults'});},deliver(kind,p){
    if(kind==='hubDefaults'){home=p.home;values.destination||=home+'/Sovereign Hub';values.config||=values.destination+'/config.json';render();}
    if(kind==='hubPicked'){values[p.field]=p.path;ready=false;render();}
    if(kind==='hubResult'){if(!pending||p.request!==pending.request)return;const previous=pending;pending=null;result=p;ready=p.exit===0&&!p.error&&!previous?.apply&&!['status','doctor'].includes(previous?.command);if(p.applied&&p.config?.destination)values.config=p.config.destination+'/config.json';render();}
  }};
})();
