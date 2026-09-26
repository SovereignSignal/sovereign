/* Archive backups use their authoritative host, independently of VM monitoring. */
window.SovBackups=(()=>{
  let host=null,root=null,state=null,result=null,pending=null,ready=false,action='configure',browser=null;
  const values={folder:'',key:'',backup:'',destination:''};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const post=o=>window.webkit.messageHandlers.sov.postMessage(o);
  const stamp=t=>t?new Date(t*1000).toLocaleString():'None recorded';
  const names={configure:'Save destination',backup:'Back up now',verify:'Verify backup',restore:'Restore to a new folder'};
  const fields={configure:['folder','key'],backup:[],verify:['backup'],restore:['backup','key','destination']};
  const labels={folder:'Backup folder',key:'Recovery key file',backup:'Backup file',destination:'New restore folder'};
  function send(op,apply=false,extra={}){
    if(pending||!root)return;
    const request=crypto.randomUUID();const payload={cmd:'archiveBackup',protocol:1,root,action:op,apply,request,...extra};
    if(fields[op])for(const f of fields[op])payload[f]=values[f];
    if(apply)payload.token=result?.token;
    pending={request,op,apply};ready=false;post(payload);render();
  }
  function render(){
    if(!host?.isConnected)return;
    const dest=state?.destinations?.[0],busy=!!pending,remote=state?.remote,owner=state?.executor||state?.host;
    const hasState=state&&!state.error;
    host.className='';host.innerHTML=`<section class="hub-form archive-backups" aria-label="Archive backups">
      <h2>Backups</h2><p>${esc(root?.split('/').pop()||'Open an archive')} ${owner?'· Backups run on '+esc(owner):''}</p>
      <p>Recover your archive, decisions and operating settings. Computers and VM images have their own backups.</p>
      <div class="acts"><button id="ab-refresh" ${busy?'disabled':''}>Refresh</button><button data-goto-view="backups">Infrastructure copies</button></div>
      ${state?.error?`<p role="alert">${esc(state.error)}</p><p>The last backup status could not be checked. No local mirror was used as a substitute.</p>`:''}
      ${dest?`<section class="ab-card"><h3>${state.error?'Destination status unavailable':dest.available?'Destination connected':'Destination unavailable'}</h3><p class="ab-path">${esc(dest.folder)}</p>${dest.problem?`<p role="alert">${esc(dest.problem)}</p>`:''}
        <dl><dt>Last completed backup</dt><dd>${esc(stamp(dest.last_success?.finished))}</dd><dt>Last attempt</dt><dd>${esc(dest.last_attempt?.state||'None recorded')}${dest.last_attempt?.error?' · '+esc(dest.last_attempt.error):''}</dd><dt>Integrity</dt><dd>${dest.last_success?.integrity_verified?'Verified when saved':'Not verified'}</dd><dt>Last restore drill</dt><dd>${esc(stamp(dest.last_restore?.finished))}</dd></dl>
        <p>Last successful status check: ${esc(stamp(state.observed_at))}${state.error?'. These are previously observed receipts.':''}</p>
        ${dest.same_disk?'<p>This destination is on the archive’s disk. Use another disk or NAS for disk-failure protection.</p>':''}
        <p class="ab-path">Recovery key: ${esc(dest.key)}. Keep a separate secure copy.</p></section>`:hasState?'<p>No backup destination configured for this archive.</p>':''}
      ${hasState?`<div class="acts ab-actions">${Object.entries(names).map(([k,n])=>`<button data-ab-action="${k}" aria-pressed="${action===k}" ${busy||(k!=='configure'&&k!=='restore'&&!dest)?'disabled':''}>${k==='configure'&&dest?'Change destination':n}</button>`).join('')}</div>
      <h3>${esc(names[action])}</h3>${remote?`<p>Choose paths on ${esc(owner)}. A drive attached only to this Mac is not a destination on that host.</p>`:''}
      <div class="fields">${fields[action].map(f=>`<label>${esc(labels[f])}<input data-ab-field="${f}" value="${esc(values[f])}" autocomplete="off" spellcheck="false" ${busy?'disabled':''}><button data-ab-pick="${f}" ${busy?'disabled':''}>Choose…</button></label>`).join('')}</div>
      ${action==='configure'?'<p>An existing recovery key can be reused. A new key is created at the chosen path when you save. Nothing is scheduled automatically.</p>':''}
      ${action==='restore'?'<p>Verify and recover into a new folder. Restored connections and schedules remain inactive.</p>':''}
      <div class="acts"><button id="ab-preview" ${busy?'disabled':''}>${busy?'Working…':'Preview'}</button><button id="ab-apply" class="brass" ${busy||!ready?'disabled':''}>${esc(names[action])}</button></div>`:''}
      ${browser?`<section class="ab-browser"><h3>Choose on ${esc(owner||'this computer')}</h3><p class="ab-path">${esc(browser.folder)}</p><div class="acts"><button id="ab-up" ${busy?'disabled':''}>Parent folder</button>${browser.field==='folder'?`<button id="ab-use-folder" ${busy?'disabled':''}>Use this folder</button>`:''}<button id="ab-close-browser" ${busy?'disabled':''}>Close</button></div>${browser.entries.map(e=>`<button class="ab-entry" data-ab-entry="${esc(e.path)}" data-directory="${e.directory}" ${busy?'disabled':''}>${e.directory?'Folder: ':''}${esc(e.name)}</button>`).join('')}<p>You can also enter a complete path above.</p></section>`:''}
      <div role="status" aria-live="polite">${busy?'<p>The archive host is working. Large backups may take several minutes.</p>':''}${result?.error?`<p class="ab-error">${esc(result.error)}</p>`:''}
      ${result&&!result.error?summary(result):''}</div>
      <details><summary>What this protects</summary><p>${esc(state?.scope||'Only content present on the authoritative archive host is included.')}</p><p>Excluded: ${esc((state?.excludes||[]).join('; '))}.</p></details>
    </section>`;
  }
  function summary(p){
    if(p.applied)return `<p>${esc(p.state==='configured'?'Destination saved. Keep an independent copy of your recovery key.':p.state==='completed'?'Backup saved and integrity verified.':p.state==='restored'?'Restore completed. The recovered archive is inactive.':'Backup integrity verified.')}</p>${p.backup?`<p class="ab-path">${esc(p.backup)}</p>`:''}${p.destination?`<p class="ab-path">${esc(p.destination)}</p>`:''}`;
    if(!p.token)return '';
    if(p.action==='configure')return `<p>Save ${esc(p.folder)}${p.create_key?' and create a recovery key at '+esc(p.key):' using the existing recovery key'}. No schedule will be enabled.</p>${p.same_disk?'<p>This folder shares the archive’s disk.</p>':''}`;
    if(p.action==='backup')return `<p>Back up ${p.files.toLocaleString()} files (${(p.source_bytes/1048576).toFixed(1)} MiB) on ${esc(p.host)}. Existing backups will be preserved.</p>`;
    return `<p>${p.action==='restore'?'Restore into '+esc(p.destination)+'. Existing data and active connections stay in place.':'Authenticate the selected backup and verify every saved file.'}</p>`;
  }
  document.addEventListener('input',e=>{const f=e.target.dataset.abField;if(f){values[f]=e.target.value;ready=false;result=null;const b=document.querySelector('#ab-apply');if(b)b.disabled=true;}});
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b||pending)return;
    if(b.id==='ab-refresh')send('status');
    if(b.dataset.abAction){action=b.dataset.abAction;result=null;ready=false;browser=null;render();}
    if(b.id==='ab-preview')send(action);
    if(b.id==='ab-apply'&&ready)send(action,true);
    if(b.dataset.abPick){if(state?.remote){browser={field:b.dataset.abPick,folder:state.home,entries:[]};send('browse',false,{folder:state.home});}else post({cmd:'archiveBackupPick',field:b.dataset.abPick});}
    if(b.dataset.abEntry){if(b.dataset.directory==='true')send('browse',false,{folder:b.dataset.abEntry});else if(browser&&['backup','key'].includes(browser.field)){values[browser.field]=b.dataset.abEntry;browser=null;result=null;ready=false;render();}}
    if(b.id==='ab-up')send('browse',false,{folder:browser.parent});
    if(b.id==='ab-use-folder'){values[browser.field]=browser.folder;browser=null;ready=false;result=null;render();}
    if(b.id==='ab-close-browser'){browser=null;render();}
  });
  return {get busy(){return !!pending;},mount(el,archive){const changed=root!==archive;host=el;if(changed){root=archive;state=null;result=null;ready=false;browser=null;for(const k in values)values[k]='';}render();if(!state&&!pending&&root)send('status');},deliver(kind,p){
    if(kind==='archiveBackupPicked'){if(p.field in values){values[p.field]=p.path;ready=false;result=null;render();}return;}
    if(kind!=='archiveBackupResult'||p.request!==pending?.request)return;
    const old=pending;pending=null;
    if(old.op==='status'){state=p.error?{...state,...p}:p;const d=p.destinations?.[0];values.folder=d?.folder||values.folder;values.key=d?.key||values.key||(p.home?p.home+'/sovereign-recovery.key':'');values.backup=d?.last_success?.backup||values.backup;render();return;}
    if(old.op==='browse'){if(p.error)result=p;else browser={...browser,...p};render();return;}
    result=p;ready=!old.apply&&!p.error&&p.exit===0&&!!p.token;
    if(old.apply&&!p.error){if(p.backup)values.backup=p.backup;send('status');return;}
    render();
  }};
})();
