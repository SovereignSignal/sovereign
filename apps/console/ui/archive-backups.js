/* Archive backups use their authoritative host, independently of VM monitoring. */
window.SovBackups=(()=>{
  let host=null,root=null,state=null,result=null,pending=null,ready=false,action='configure',browser=null,storage='external';
  const values={folder:'',key:'',backup:'',destination:''};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const post=o=>window.webkit.messageHandlers.sov.postMessage(o);
  const stamp=t=>t?new Date(t*1000).toLocaleString():'None recorded';
  const names={backup:'Back up now',restore:'Restore to a new folder',verify:'Check saved backup',reconnect:'Reconnect folder',configure:'Save destination'};
  const fields={configure:['folder','key'],reconnect:['folder'],backup:[],verify:['backup'],restore:['backup','key','destination']};
  const labels={folder:'Backup folder',key:'Recovery key file',backup:'Backup file',destination:'New restore folder'};
  const storageChoices={external:['External drive','Connect your USB or external drive to the archive computer. Choose a dedicated folder on that drive.'],network:['NAS or network folder','Connect the shared folder in Finder on the archive computer, then choose a folder inside it.'],folder:['Folder on this computer','Choose a folder outside the archive. A copy on the same disk cannot protect against that disk failing.']};
  function protection(s){
    const d=s?.destinations?.[0];
    if(!s||s.error)return {title:'Backup protection needs a fresh check',detail:'The archive host could not be checked. Previously observed receipts may be out of date.',next:'Refresh backup status',op:'status'};
    if(!d)return {title:'Save your first backup',detail:'Choose a folder, external drive or NAS reachable by the archive computer.',next:'Choose a destination',op:'configure'};
    if(!d.available)return {title:'Your backup destination needs attention',detail:'Connect the original storage and check the recovery key on the archive computer. The details below explain what failed.',next:'Refresh after reconnecting',op:'status'};
    if(!d.last_success?.backup_id)return {title:'Your destination is ready for its first backup',detail:'Saving a destination does not save your archive. Run a backup to create a recovery copy.',next:'Back up now',op:'backup'};
    if(d.latest_present===undefined||d.latest_restored===undefined)return {title:'Update the archive host to check protection',detail:'This host cannot report whether the saved copy is still present and its restore test matches.',next:'Refresh after updating',op:'status'};
    if(!d.latest_present)return {title:'The latest saved copy is missing or changed',detail:'The previous receipt is not proof that this file is still usable. Create a new backup.',next:'Back up now',op:'backup'};
    if(!d.latest_restored)return {title:'Your saved backup needs a restore test',detail:'Recover it into a new folder to check that your archive can be opened. Existing files stay in place.',next:'Test a restore',op:'restore'};
    if(d.same_disk)return {title:'Restore tested. Add protection against disk failure',detail:'This backup shares the archive’s disk. Choose an external drive or NAS for a separate copy.',next:'Choose another destination',op:'configure'};
    return {title:'Your latest saved backup passed a restore test',detail:'Changes since that backup still need saving. Automatic backups and independent offsite recovery need setup.',next:'Back up now',op:'backup'};
  }
  function age(t,observed){
    if(!Number.isFinite(t)||!Number.isFinite(observed)||t>observed)return 'Age unavailable';
    const minutes=Math.floor((observed-t)/60);
    return minutes<1?'Less than a minute old':minutes<60?`${minutes} minutes old`:minutes<1440?`${Math.floor(minutes/60)} hours old`:`${Math.floor(minutes/1440)} days old`;
  }
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
    const assessment=protection(state);
    host.className='';host.innerHTML=`<section class="hub-form archive-backups" aria-label="Archive backups">
      ${state?`<section class="ab-readiness" aria-label="Backup protection"><h3>${esc(assessment.title)}</h3><p>${esc(assessment.detail)}</p><div class="acts"><button id="ab-next" class="brass" ${busy?'disabled':''}>${esc(assessment.next)}</button><button id="ab-refresh" ${busy?'disabled':''}>Refresh</button></div></section>`:`<p>${root?'Checking…':'Open an archive'}</p>`}
      ${hasState?`<p class="ab-mode">On demand · Automatic backups are not enabled${owner?' · runs on '+esc(owner):''}</p>`:''}
      ${state?.error?`<p role="alert">${esc(state.error)}</p><p>The last backup status could not be checked. No local mirror was used as a substitute.</p>`:''}
      ${dest?`<section class="ab-card"><h3>${state.error?'Destination status unavailable':dest.available?'Destination connected':'Destination unavailable'}</h3><p class="ab-path">${esc(dest.folder)}</p>${dest.problem?`<p role="alert">${esc(dest.problem)}</p>`:''}
        <dl><dt>Last saved backup</dt><dd>${esc(stamp(dest.last_success?.finished))}</dd><dt>Saved copy</dt><dd>${state.error?'Status unavailable':!dest.available?'Reconnect to check':dest.latest_present===undefined?'Update the archive host to check this copy':dest.latest_present?'Available · verified when saved':dest.last_success?.backup_id?'Missing or size changed · check the destination':'No backup saved yet'}</dd><dt>Latest backup recovery</dt><dd>${dest.latest_restored===undefined?'Update the archive host to check recovery':dest.latest_restored?'Restore tested · '+esc(stamp(dest.last_restore?.finished)):dest.last_success?.backup_id?'Restore test needed':'Create a backup first'}</dd><dt>Last attempt</dt><dd>${esc(dest.last_attempt?.state||'None recorded')}${dest.last_attempt?.error?' · '+esc(dest.last_attempt.error):''}</dd></dl>
        ${dest.last_restore?.finished&&dest.latest_restored===false?`<p>An earlier backup was restored on ${esc(stamp(dest.last_restore.finished))}. The latest backup still needs a restore test.</p>`:''}
        <p class="ab-observed">Last successful status check: ${esc(stamp(state.observed_at))}${state.error?'. These are previously observed receipts.':''}</p>
        ${dest.last_success?.finished?`<p class="ab-age">Backup age at that check: ${esc(age(dest.last_success.finished,state.observed_at))}. Work received after ${esc(stamp(dest.last_success.started||dest.last_success.finished))} may be missing from this copy.</p>`:''}
        ${dest.same_disk?'<p>This destination is on the archive’s disk. Use another disk or NAS for disk-failure protection.</p>':''}
        ${!dest.available&&!state.error?`<p>Connect the disk or NAS on ${esc(owner||'the archive computer')} and refresh. If its folder path changed, use Reconnect folder to keep its backup history.</p>`:''}
        <details><summary>Recovery key and scope</summary><p class="ab-path">Recovery key: ${esc(dest.key)}. Keep a separate secure copy. Losing the key makes the backup unreadable.</p><p>Computers, external credentials and VM images have their own recovery requirements.</p></details></section>`:hasState?'<p>No backup destination configured for this archive.</p>':''}
      ${hasState?`<details class="ab-coverage"><summary>What still needs attention</summary><dl><dt>Automatic backups</dt><dd>Not enabled. Run Back up now when you need a fresh copy.</dd><dt>Old backups</dt><dd>Kept until you remove them. Automatic cleanup is not configured.</dd><dt>Offsite recovery</dt><dd>Not verified here. A NAS or external drive kept in the same building does not cover loss of that location.</dd><dt>Separate recovery key</dt><dd>Independent copy not verified here. Keep a secure copy somewhere you could access after losing this computer.</dd><dt>Work from other devices</dt><dd>Only work received by the archive can be backed up. Backup success does not confirm every producer has delivered its latest work.</dd></dl><button data-goto-view="sources">Sources</button></details>`:''}
      ${hasState?`<div class="acts ab-actions">${Object.entries(names).map(([k,n])=>`<button data-ab-action="${k}" aria-pressed="${action===k}" ${busy||(k!=='configure'&&k!=='restore'&&!dest)||(['backup','verify'].includes(k)&&!dest?.available)?'disabled':''}>${k==='configure'&&dest?'Change destination':n}</button>`).join('')}</div>
      <h3>${esc(names[action])}</h3>${remote?`<p>Choose paths on ${esc(owner)}. A drive attached only to this Mac is not a destination on that host.</p>`:''}
      ${action==='configure'?`<fieldset class="ab-storage"><legend>Where will you save your backup?</legend><div class="acts">${Object.entries(storageChoices).map(([k,v])=>`<button data-ab-storage="${k}" aria-pressed="${storage===k}" ${busy?'disabled':''}>${esc(v[0])}</button>`).join('')}</div><p>${esc(storageChoices[storage][1])}</p><p>These choices guide folder selection. Sovereign uses the folder you choose and does not format drives. Cloud services without a mounted folder are not supported here.</p>${dest?'<p>One active destination per archive. Changing it keeps old backup files and archives their history; it does not add a second destination.</p>':''}</fieldset>`:''}
      <div class="fields">${fields[action].map(f=>`<label>${esc(labels[f])}<input data-ab-field="${f}" value="${esc(values[f])}" autocomplete="off" spellcheck="false" ${busy?'disabled':''}><button data-ab-pick="${f}" ${busy?'disabled':''}>Choose…</button></label>`).join('')}</div>
      ${action==='reconnect'?'<p>Choose the original backup folder after connecting your disk or NAS. Its identity must match; existing backups, recovery key and history are preserved.</p>':''}
      ${action==='configure'?'<p>An existing recovery key can be reused. A new key is created at the chosen path when you save. Nothing is scheduled automatically.</p>':''}
      ${action==='restore'?'<p>Verify and recover into a new folder. Restored connections and schedules remain inactive.</p>':''}
      <div class="acts"><button id="ab-preview" ${busy||(['backup','verify'].includes(action)&&!dest?.available)?'disabled':''}>${busy?'Working…':'Preview'}</button><button id="ab-apply" class="brass" ${busy||!ready?'disabled':''}>${esc(names[action])}</button></div>`:''}
      ${browser?`<section class="ab-browser"><h3>Choose on ${esc(owner||'this computer')}</h3><p class="ab-path">${esc(browser.folder)}</p><div class="acts"><button id="ab-volumes" ${busy?'disabled':''}>Connected drives</button><button id="ab-home" ${busy?'disabled':''}>Home folder</button><button id="ab-up" ${busy?'disabled':''}>Parent folder</button>${browser.field==='folder'?`<button id="ab-use-folder" ${busy?'disabled':''}>Use this folder</button>`:''}<button id="ab-close-browser" ${busy?'disabled':''}>Close</button></div>${browser.entries.map(e=>`<button class="ab-entry" data-ab-entry="${esc(e.path)}" data-directory="${e.directory}" ${busy?'disabled':''}>${e.directory?'Folder: ':''}${esc(e.name)}</button>`).join('')}<p>You can also enter a complete path above.</p></section>`:''}
      <div role="status" aria-live="polite">${busy?'<p>The archive host is working. Large backups may take several minutes.</p>':''}${result?.error?`<p class="ab-error">${esc(result.error)}</p>`:''}
      ${result&&!result.error?summary(result):''}</div>
      <details><summary>What this protects</summary><p>${esc(state?.scope||'Only content present on the authoritative archive host is included.')}</p><p>Excluded: ${esc((state?.excludes||[]).join('; '))}.</p></details>
    </section>`;
  }
  function summary(p){
    if(p.applied)return `<p>${esc(p.state==='reconnected'?'Backup folder reconnected. Existing backup history is preserved.':p.state==='configured'?'Destination saved. Keep an independent copy of your recovery key.':p.state==='completed'?'Backup saved and integrity verified.':p.state==='restored'?'Restore completed. The recovered archive is inactive.':'Backup integrity verified.')}</p>${p.backup?`<p class="ab-path">${esc(p.backup)}</p>`:''}${p.destination?`<p class="ab-path">${esc(p.destination)}</p>`:''}`;
    if(!p.token)return '';
    if(p.action==='reconnect')return `<p>Reconnect the existing destination at ${esc(p.folder)}. The key and backup history stay in place.</p>`;
    if(p.action==='configure')return `<p>Save ${esc(p.folder)}${p.create_key?' and create a recovery key at '+esc(p.key):' using the existing recovery key'}. No schedule will be enabled.</p>${p.same_disk?'<p>This folder shares the archive’s disk.</p>':''}`;
    if(p.action==='backup')return `<p>Back up ${p.files.toLocaleString()} files (${(p.source_bytes/1048576).toFixed(1)} MiB) on ${esc(p.host)}. Existing backups will be preserved. If files change during collection, Sovereign retries once.</p>`;
    return `<p>${p.action==='restore'?'Restore into '+esc(p.destination)+'. Existing data and active connections stay in place.':'Authenticate the selected backup and verify every saved file.'}</p>`;
  }
  document.addEventListener('input',e=>{const f=e.target.dataset.abField;if(f){values[f]=e.target.value;ready=false;result=null;const b=document.querySelector('#ab-apply');if(b)b.disabled=true;}});
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b||pending)return;
    if(b.id==='ab-refresh')send('status');
    if(b.id==='ab-next'){const next=protection(state).op;if(next==='status')send('status');else {action=next;result=null;ready=false;browser=null;render();document.querySelector('#ab-preview')?.scrollIntoView({block:'nearest'});}}
    if(b.dataset.abStorage){storage=b.dataset.abStorage;browser=null;result=null;ready=false;render();}
    if(b.dataset.abAction){action=b.dataset.abAction;result=null;ready=false;browser=null;render();}
    if(b.id==='ab-preview')send(action);
    if(b.id==='ab-apply'&&ready)send(action,true);
    if(b.dataset.abPick){const drives=b.dataset.abPick==='folder'&&(action==='reconnect'||storage!=='folder');if(state?.remote){const start=drives?'/Volumes':state.home;browser={field:b.dataset.abPick,folder:start,entries:[]};send('browse',false,{folder:start});}else post({cmd:'archiveBackupPick',field:b.dataset.abPick,action,location:drives?'volumes':'home'});}
    if(b.dataset.abEntry){if(b.dataset.directory==='true')send('browse',false,{folder:b.dataset.abEntry});else if(browser&&['backup','key'].includes(browser.field)){values[browser.field]=b.dataset.abEntry;browser=null;result=null;ready=false;render();}}
    if(b.id==='ab-volumes')send('browse',false,{folder:'/Volumes'});
    if(b.id==='ab-home')send('browse',false,{folder:state.home});
    if(b.id==='ab-up')send('browse',false,{folder:browser.parent});
    if(b.id==='ab-use-folder'){values[browser.field]=browser.folder;browser=null;ready=false;result=null;render();}
    if(b.id==='ab-close-browser'){browser=null;render();}
  });
  return {protection,age,get busy(){return !!pending;},mount(el,archive){const changed=root!==archive;host=el;if(changed){root=archive;action='configure';storage='external';state=null;result=null;ready=false;browser=null;for(const k in values)values[k]='';}render();if(!state&&!pending&&root)send('status');},deliver(kind,p){
    if(kind==='archiveBackupPicked'){if(p.field in values){values[p.field]=p.path;ready=false;result=null;render();}return;}
    if(kind!=='archiveBackupResult'||p.request!==pending?.request)return;
    const old=pending;pending=null;
    if(old.op==='status'){const initial=!state;state=p.error?{...state,...p}:p;const d=p.destinations?.[0];values.folder=d?.folder||values.folder;values.key=d?.key||values.key||(p.home?p.home+'/sovereign-recovery.key':'');values.backup=d?.last_success?.backup_id?d.folder+'/'+d.last_success.backup_id+'.sovbackup':values.backup;if(d&&(initial||result?.state==='configured'||result?.state==='reconnected'))action='backup';render();return;}
    if(old.op==='browse'){if(p.error)result=p;else browser={...browser,...p};render();return;}
    result=p;ready=!old.apply&&!p.error&&p.exit===0&&!!p.token;
    if(old.apply&&!p.error){if(p.backup)values.backup=p.backup;send('status');return;}
    render();
  }};
})();
