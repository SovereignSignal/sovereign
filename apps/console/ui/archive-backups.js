/* Archive backups use their authoritative host, independently of VM monitoring.
 * The face is a verdict that states the backup's age once, one sentence, and four rows that
 * each carry their own action. Rare actions sit under More; paths, ids, hosts and receipts
 * fold under Details. The step that previews and applies a change opens under the rows only
 * when one is chosen, and the status check time is evidence for the header time's tooltip. */
window.SovBackups=(()=>{
  let host=null,root=null,state=null,result=null,pending=null,ready=false,action='configure',browser=null,storage='external',open=false,seen=false;
  const values={folder:'',key:'',backup:'',destination:''};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const post=o=>window.webkit.messageHandlers.sov.postMessage(o);
  const stamp=t=>t?new Date(t*1000).toLocaleString():'None recorded';
  const day=t=>new Date(t*1000).toLocaleDateString([],{month:'short',day:'numeric'});
  const names={backup:'Back up now',restore:'Restore to a new folder',verify:'Check saved backup',reconnect:'Reconnect folder',configure:'Save destination'};
  // What a running change is called where navigation says it is waiting for it.
  const running={backup:'Backup',restore:'Restore',verify:'Backup check',reconnect:'Reconnect',configure:'Destination change'};
  const fields={configure:['folder','key'],reconnect:['folder'],backup:[],verify:['backup'],restore:['backup','key','destination']};
  const labels={folder:'Backup folder',key:'Recovery key file',backup:'Backup file',destination:'New restore folder'};
  const storageChoices={external:['External drive','Connect your USB or external drive to the archive computer. Choose a dedicated folder on that drive.'],network:['NAS or network folder','Connect the shared folder in Finder on the archive computer, then choose a folder inside it.'],folder:['Folder on this computer','Choose a folder outside the archive. A copy on the same disk cannot protect against that disk failing.']};
  const notes={backup:'Preview shows what will be saved before anything runs.',configure:'A recovery key that exists is reused; otherwise one is created at that path. Nothing is scheduled.',reconnect:'Connect the disk or NAS, then choose the original folder. Its backups, key and history are kept.',restore:'Recovers into a new folder. Restored connections and schedules stay off.'};
  // What the owner should do next, in order of what protects the archive most.
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
  // How long before the status check the backup finished, as the headline says it.
  function since(t,observed){
    if(!Number.isFinite(t)||!Number.isFinite(observed)||t>observed)return null;
    const m=Math.floor((observed-t)/60),n=(v,u)=>`${v} ${u}${v===1?'':'s'} ago`;
    return m<1?'moments ago':m<60?n(m,'minute'):m<1440?n(Math.floor(m/60),'hour'):n(Math.floor(m/1440),'day');
  }
  // The headline states the backup's age once; its sentence says the one thing that matters most.
  function verdict(s){
    if(!s)return null;
    const d=s.destinations?.[0],saved=d?.last_success,owner=s.executor||s.host;
    const ago=saved?.finished?since(saved.finished,s.observed_at):null;
    const last=ago?'Last backup '+ago:saved?.finished?'Last backup '+day(saved.finished):'Last backup age unknown';
    if(s.error)return {dot:'warn',headline:'Backup status needs a fresh check',say:String(s.error).replace(/([^.!?])$/,'$1.')+(d?' Rows show the last receipts.':'')};
    if(!d)return {dot:'warn',headline:'No backup yet',say:'Choose a drive, NAS or folder the archive computer can reach.'};
    if(!d.available)return {dot:'down',headline:'Backup destination not connected',say:`Connect it on ${owner||'the archive computer'}, then refresh. If its folder moved, reconnect it under More.`};
    if(!saved?.backup_id)return {dot:'warn',headline:'No backup yet',say:'The destination is ready. Saving it did not back anything up.'};
    if(d.latest_present===undefined||d.latest_restored===undefined)return {dot:'warn',headline:last,say:'Update the archive host to check this copy and its restore test.'};
    if(!d.latest_present)return {dot:'down',headline:'Latest backup missing',say:'The saved file is missing or changed, so it no longer proves a usable copy. Back up again.'};
    const work=`Work since ${day(saved.started||saved.finished)} is not in it yet.`;
    if(!d.latest_restored)return {dot:'warn',headline:last,say:'It has not passed a restore test. '+work};
    if(d.same_disk)return {dot:'warn',headline:last,say:'It passed a restore test, but it shares the archive’s disk, so one disk failure loses both.'};
    return {dot:ago&&s.observed_at-saved.finished<172800?'live':'warn',headline:last,say:'It passed a restore test. '+work};
  }
  // A drive or share is named by its volume; anything else by its folder. The full path is its tooltip.
  const place=f=>{const m=/^\/Volumes\/([^/]+)/.exec(f||'');return m?m[1]:String(f||'').split('/').filter(Boolean).pop()||String(f||'');};
  // Four rows: a dot, a name, its value in mono and at most one action. An action the verdict
  // already offers is not offered twice, and a stale reading offers none.
  function rows(s,op){
    const d=s.destinations?.[0],err=!!s.error,saved=d?.last_success,r=d?.last_restore,busy=!!pending;
    const act=(k,label)=>err||k===op?'':`<button data-ab-action="${k}" aria-expanded="${open&&action===k}" aria-controls="ab-step" ${busy?'disabled':''}>${label}</button>`;
    const where=d?place(d.folder):'';
    const list=[
      ['destination','Destination',...(!d?['warn','not set']:err?['idle',where+' · unchecked']:!d.available?['down',where+' · not connected']:d.same_disk?['warn',where+' · same disk']:['live',where+' · connected']),d?.folder,act('configure',d?'Change…':'Choose…')],
      ['schedule','Schedule',...(s.scheduled?['live','on']:['warn','off']),s.scheduled?'':'Backups run only when you choose Back up now.',''],
      ['offsite','Offsite copy','warn','not verified','A drive or NAS kept in the same building does not cover the loss of that place.',''],
      ['restore','Restore test',...(!saved?.backup_id?['idle','none yet']:d.latest_restored===undefined?['idle','unknown']:d.latest_restored?['live',(r?.finished?day(r.finished)+' · ':'')+'passed']:['warn','not run']),
        d?.latest_restored===undefined&&saved?.backup_id?'Update the archive host to check recovery.':d?.latest_restored?'Restored '+stamp(r?.finished):r?.finished?'An earlier backup was restored '+stamp(r.finished)+'.':'',
        act('restore',d?.latest_restored?'Test again':saved?.backup_id?'Test…':'Restore…')]];
    return `<div class="ab-rows" role="list">${list.map(([key,name,dot,value,tip,button])=>`<div class="ab-row" role="listitem" data-ab-row="${key}"><span class="dot ${err?'idle':dot}" aria-hidden="true"></span><span class="ab-name">${name}</span><span class="ab-value"${tip?` title="${esc(tip)}"`:''}>${esc(value)}</span>${button||'<span></span>'}</div>`).join('')}</div>`;
  }
  // Rare actions. Each appears only where it can run.
  function more(s,op){
    if(s.error)return '';
    const d=s.destinations?.[0],busy=pending?'disabled':'',items=[];
    const item=k=>`<button data-ab-action="${k}" aria-expanded="${open&&action===k}" aria-controls="ab-step" ${busy}>${k==='verify'?'Check a backup':names[k]}</button>`;
    if(d?.available&&op!=='backup')items.push(item('backup'));
    if(d?.available)items.push(item('verify'));
    if(d)items.push(item('reconnect'));
    if(op!=='status')items.push(`<button id="ab-refresh" ${busy}>Refresh status</button>`);
    return items.length?`<details class="ab-more"><summary aria-label="More backup actions">More</summary><div class="ab-menu">${items.join('')}</div></details>`:'';
  }
  // Technical evidence, folded: where things are, which backup, which host, what failed.
  function details(s,opened){
    const d=s.destinations?.[0],saved=d?.last_success,att=d?.last_attempt,ver=d?.last_verification,r=d?.last_restore,facts=[];
    const fact=(k,v,mono)=>{if(v)facts.push(`<dt>${k}</dt><dd${mono?' class="mono"':''}>${esc(v)}</dd>`);};
    fact('Runs on',s.executor||s.host,true);
    fact('Folder',d?.folder,true);
    fact('Problem',d?.problem);
    fact('Recovery key',d?.key,true);
    if(d)fact('Key copy','Independent copy not verified. Without the key the backup is unreadable.');
    fact('Last backup',saved?.finished&&stamp(saved.finished)+(saved.backup_id?' · '+saved.backup_id:''));
    if(d&&saved?.backup_id)fact('Saved copy',s.error?'Status unavailable':!d.available?'Reconnect to check':d.latest_present===undefined?'Update the archive host to check this copy':d.latest_present?'Available · verified when saved':'Missing or size changed');
    fact('Last check',ver?.finished&&stamp(ver.finished)+(ver.state?' · '+ver.state:''));
    fact('Restore test',r?.finished&&stamp(r.finished)+(r.backup_id?' · '+r.backup_id:''));
    fact('Last attempt',att?.state&&att.state+(att.error?' · '+att.error:''));
    fact('Included',s.scope||'Only content present on the authoritative archive host is included.');
    fact('Excluded',(s.excludes||[]).join('; '));
    fact('Not covered','Work other devices have not delivered yet, device setups, external credentials and VM images. Old backups stay until you remove them.');
    return `<details class="ab-details"${opened?' open':''}><summary>Details</summary><dl>${facts.join('')}</dl></details>`;
  }
  // The step that previews and applies the chosen change.
  function step(s,said){
    if(!open||s.error)return '';
    const dest=s.destinations?.[0],busy=!!pending,owner=s.executor||s.host,off=busy?'disabled':'';
    return `<section class="ab-step" id="ab-step" aria-label="${esc(names[action])}">
      ${s.remote&&fields[action].length?`<p>Paths are on ${esc(owner)}. A drive attached only to this Mac does not count.</p>`:''}
      ${action==='configure'?`<fieldset class="ab-storage"><legend>Where will backups go?</legend><div class="acts">${Object.entries(storageChoices).map(([k,v])=>`<button data-ab-storage="${k}" aria-pressed="${storage===k}" ${off}>${esc(v[0])}</button>`).join('')}</div><p>${esc(storageChoices[storage][1])}</p><p>Sovereign uses the folder you choose and does not format drives. Cloud services need a mounted folder.${dest?' One destination per archive: changing it keeps old backups and their history.':''}</p></fieldset>`:''}
      ${fields[action].length?`<div class="fields">${fields[action].map(f=>`<label>${esc(labels[f])}<input data-ab-field="${f}" value="${esc(values[f])}" autocomplete="off" spellcheck="false" ${off}><button data-ab-pick="${f}" ${off}>Choose…</button></label>`).join('')}</div>`:''}
      ${notes[action]?`<p>${esc(notes[action])}</p>`:''}
      <div class="acts"><button id="ab-preview" ${busy||(['backup','verify'].includes(action)&&!dest?.available)?'disabled':''}>${busy?'Working…':'Preview'}</button><button id="ab-apply" class="brass" ${busy||!ready?'disabled':''}>${esc(names[action])}</button><button id="ab-close-step" class="quiet" ${off}>${result?.applied?'Done':'Cancel'}</button></div>
      ${said}
      ${browser?`<section class="ab-browser"><h3>Choose on ${esc(owner||'this computer')}</h3><p class="ab-path">${esc(browser.folder)}</p><div class="acts"><button id="ab-volumes" ${off}>Connected drives</button><button id="ab-home" ${off}>Home folder</button><button id="ab-up" ${off}>Parent folder</button>${['folder','destination'].includes(browser.field)?`<button id="ab-use-folder" ${off}>Use this folder</button>`:''}<button id="ab-close-browser" ${off}>Close</button></div>${browser.entries.map(e=>`<button class="ab-entry" data-ab-entry="${esc(e.path)}" data-directory="${e.directory}" ${off}>${e.directory?'Folder: ':''}${esc(e.name)}</button>`).join('')}<p>You can also enter a complete path above.</p></section>`:''}
    </section>`;
  }
  // When backup status was last read is evidence: it rides on the header time's tooltip.
  function caption(){
    const t=document.querySelector('#vmeta');
    if(!t||document.body?.dataset.view!=='recovery'||!Number.isFinite(state?.observed_at))return;
    const base=String(t.title||'').replace(/(^| · )Backups checked.*$/,'');
    t.title=(base?base+' · ':'')+'Backups checked '+stamp(state.observed_at)+(state.error?', refresh failed':'');
  }
  // A quiet send is a refresh's re-check of a failed read: it draws no busy state, and its
  // reply redraws only when the answer differs from the one on screen.
  function send(op,apply=false,extra={},quiet=false){
    if(pending||!root)return;
    const request=crypto.randomUUID();const payload={cmd:'archiveBackup',protocol:1,root,action:op,apply,request,...extra};
    if(fields[op])for(const f of fields[op])payload[f]=values[f];
    if(apply)payload.token=result?.token;
    pending={request,op,apply,root,quiet};ready=false;post(payload);if(!quiet)render();
  }
  // #rows hosts every view, so a reply that lands after the owner moved on must not paint into another one.
  function render(){
    if(!host?.isConnected||document.body.dataset.view!=='recovery')return;
    const busy=!!pending,opened=!!host.querySelector?.('.ab-details')?.open;
    const v=verdict(state),p=protection(state),saved=state?.destinations?.[0]?.last_success;
    // What the host is doing and what it answered sits in the open step, beside the buttons that asked.
    const said=`<div class="ab-result" role="status" aria-live="polite">${busy?'<p>The archive host is working. Large backups may take several minutes.</p>':''}${result?.error?`<p class="ab-error">${esc(result.error)}</p>`:''}${result&&!result.error?summary(result):''}</div>`;
    const drawn=state?step(state,said):'',stepped=!!drawn;
    host.className='';host.innerHTML=`<section class="hub-form archive-backups" aria-label="Archive backups">
      <div class="ab-readiness" role="group" aria-label="Backup protection">${v?`<div class="ab-verdict"><span class="dot ${v.dot}" aria-hidden="true"></span><h2 class="ab-age"${saved?.finished?` title="Saved ${esc(stamp(saved.finished))}"`:''}>${esc(v.headline)}</h2><button id="ab-next" class="brass" ${p.op==='status'?'':`data-ab-action="${p.op}" aria-expanded="${open&&action===p.op}" aria-controls="ab-step"`} ${busy?'disabled':''}>${esc(p.next)}</button>${more(state,p.op)}</div>
        <p class="ab-say"${state.error?' role="alert"':''}>${esc(v.say)}</p>`:`<div class="ab-verdict"><span class="dot" aria-hidden="true"></span><h2>${root?'Checking backups…':'Open an archive'}</h2></div>`}</div>
      ${state&&(!state.error||state.destinations)?rows(state,p.op):''}
      ${stepped?drawn:said}
      ${state?details(state,opened):''}
    </section>`;
    caption();
  }
  function summary(p){
    if(p.applied)return `<p>${esc(p.state==='reconnected'?'Backup folder reconnected. Existing backup history is preserved.':p.state==='configured'?'Destination saved. Keep an independent copy of your recovery key.':p.state==='completed'?'Backup saved and integrity verified.':p.state==='restored'?'Restore completed. The recovered archive is inactive.':'Backup integrity verified.')}</p>${p.backup?`<p class="ab-path">${esc(p.backup)}</p>`:''}${p.destination?`<p class="ab-path">${esc(p.destination)}</p>`:''}`;
    if(!p.token)return '';
    if(p.action==='reconnect')return `<p>Reconnect the existing destination at ${esc(p.folder)}. The key and backup history stay in place.</p>`;
    if(p.action==='configure')return `<p>Save ${esc(p.folder)}${p.create_key?' and create a recovery key at '+esc(p.key):' using the existing recovery key'}. No schedule will be enabled.</p>${p.same_disk?'<p>This folder shares the archive’s disk.</p>':''}`;
    if(p.action==='backup')return `<p>Back up ${p.files.toLocaleString()} files (${(p.source_bytes/1048576).toFixed(1)} MiB) on ${esc(p.host)}. Existing backups will be preserved. If files change during collection, Sovereign retries once.</p>`;
    return `<p>${p.action==='restore'?'Restore into '+esc(p.destination)+'. Existing data and active connections stay in place.':'Authenticate the selected backup and verify every saved file.'}</p>`;
  }
  // Choosing an action opens its step under the rows and moves the owner there.
  function choose(k){
    action=k;open=true;result=null;ready=false;browser=null;render();
    document.querySelector('#ab-step')?.scrollIntoView?.({block:'nearest'});
    (document.querySelector('#ab-step input')||document.querySelector('#ab-preview'))?.focus?.({preventScroll:true});
  }
  document.addEventListener('input',e=>{const f=e.target.dataset.abField;if(f){values[f]=e.target.value;ready=false;result=null;const b=document.querySelector('#ab-apply');if(b)b.disabled=true;}});
  document.addEventListener('click',e=>{
    // An open More menu closes when the owner clicks anywhere outside it.
    const menu=document.querySelector('.ab-more[open]');if(menu&&!menu.contains(e.target))menu.open=false;
    const b=e.target.closest('button');if(!b)return;
    // Asking for status while a quiet re-check runs shows that one instead of a second.
    if(pending){if(pending.quiet&&['ab-refresh','ab-next'].includes(b.id)){pending.quiet=false;render();}return;}
    if(b.id==='ab-refresh'||(b.id==='ab-next'&&protection(state).op==='status'))send('status');
    else if(b.dataset.abAction)choose(b.dataset.abAction);
    if(b.id==='ab-close-step'){open=false;result=null;ready=false;browser=null;render();document.querySelector('#ab-next')?.focus?.();}
    if(b.dataset.abStorage){storage=b.dataset.abStorage;browser=null;result=null;ready=false;render();}
    if(b.id==='ab-preview')send(action);
    if(b.id==='ab-apply'&&ready)send(action,true);
    if(b.dataset.abPick){const drives=b.dataset.abPick==='folder'&&(action==='reconnect'||storage!=='folder');if(state?.remote){const start=drives?'/Volumes':state.home;browser={field:b.dataset.abPick,folder:start,entries:[]};send('browse',false,{folder:start});}else post({cmd:'archiveBackupPick',field:b.dataset.abPick,action,location:drives?'volumes':'home'});}
    if(b.dataset.abEntry){if(b.dataset.directory==='true')send('browse',false,{folder:b.dataset.abEntry});else if(browser&&['backup','key'].includes(browser.field)){values[browser.field]=b.dataset.abEntry;browser=null;result=null;ready=false;render();}}
    if(b.id==='ab-volumes')send('browse',false,{folder:'/Volumes'});
    if(b.id==='ab-home')send('browse',false,{folder:state.home});
    if(b.id==='ab-up')send('browse',false,{folder:browser.parent});
    // A restore needs a folder that does not exist yet, so it lands inside the one chosen, named as the local picker names it.
    if(b.id==='ab-use-folder'){values[browser.field]=browser.field==='destination'?browser.folder.replace(/\/$/,'')+'/Restored Sovereign':browser.folder;browser=null;ready=false;result=null;render();}
    if(b.id==='ab-close-browser'){browser=null;render();}
  });
  return {protection,age,verdict,get busy(){return !!pending?.apply;},get operation(){return pending?.apply?running[pending.op]:null;},mount(el,archive){const changed=root!==archive,drawn=!changed&&host===el&&el.firstElementChild?.classList.contains('archive-backups');host=el;if(changed){root=archive;action='configure';storage='external';state=null;result=null;ready=false;browser=null;open=false;seen=false;for(const k in values)values[k]='';}if(!drawn)render();else caption();if((!state||state.error)&&!pending&&root)send('status',false,{},drawn);},deliver(kind,p){
    if(kind==='archiveBackupPicked'){if(p.field in values){values[p.field]=p.path;ready=false;result=null;render();}return;}
    if(kind!=='archiveBackupResult'||p.request!==pending?.request)return;
    const old=pending;pending=null;
    // Reads do not hold navigation, so another archive may be open by the time one answers.
    if(old.root!==root){render();if(!state&&root)send('status');return;}
    // Native refuses a read while an earlier one runs: the host is still being checked.
    if(old.op==='status'&&p.busy){if(!old.quiet)render();setTimeout(()=>{if(!pending&&root===old.root&&(!state||state.error)&&document.body.dataset.view==='recovery')send('status',false,{},old.quiet);},3000);return;}
    if(old.op==='status'){
      const same=old.quiet&&p.error&&state?.error===p.error;state=p.error?{...state,...p}:p;const d=p.destinations?.[0];
      values.folder=d?.folder||values.folder;values.key=d?.key||values.key||(p.home?p.home+'/sovereign-recovery.key':'');values.backup=d?.last_success?.backup_id?d.folder+'/'+d.last_success.backup_id+'.sovbackup':values.backup;
      // The first answer opens setup when there is nothing to protect yet; once a destination is
      // saved or reconnected, the step moves on to the backup itself.
      if(!p.error&&!seen){seen=true;action=d?'backup':'configure';open=!d;}
      else if(d&&['configured','reconnected'].includes(old.after)){action='backup';open=true;}
      if(!same)render();return;}
    if(old.op==='browse'){if(p.error)result=p;else browser={...browser,...p};render();return;}
    result=p;ready=!old.apply&&!p.error&&p.exit===0&&!!p.token;
    if(old.apply&&!p.error){if(p.backup)values.backup=p.backup;send('status');if(pending)pending.after=p.state;return;}
    render();
  }};
})();
