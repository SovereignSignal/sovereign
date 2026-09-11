'use strict';
// A read-only projection of the app's existing observations. No discovery or writes.
(function(scope){
  const list=v=>Array.isArray(v)?v:[], text=v=>typeof v==='string'?v:'', path=v=>text(v).replace(/\/+$/,'');
  function build({root=null,status=null,context=null}={}){
    const machine=status?.machine||{}, selected=path(root||machine.vault), configured=path(machine.vault);
    const mismatch=!!(selected&&configured&&selected!==configured), unavailable=!!status?.error;
    const bound=!!selected&&selected===configured&&!mismatch&&!unavailable;
    const observed=bound?status:{}, hub=observed?.hub||{}, receipts=context?.error||!selected||(context?.root&&path(context.root)!==selected)?[]:list(context?.receipts);
    const nodes=[],edges=[],tools=[],devices=[],clients=[],notConnected=[],seen=new Map();
    function node(id,name,kind,extra={}){if(!seen.has(id)){const n={id,name,kind,...extra};seen.set(id,n);nodes.push(n);}return seen.get(id);}
    function edge(id,from,to,transport,evidence,role,detail){
      if(!seen.has(from)||!seen.has(to))return;
      const recommendation=role==='unknown'?'Verify route':role==='capture'||role==='contribution'?'Consolidate publication':role==='relay'?'Keep until direct writes are proven':'Keep boundary';
      edges.push({id,from,to,transport,evidence,role,detail,recommendation});
    }
    const archive=selected?node('archive',text(machine.vault_name)&&bound?machine.vault_name:selected.split('/').pop(),'archive',{path:selected}):null;
    const app=node('app','Sovereign','app');
    if(archive)edge('local-archive',app.id,archive.id,'Local archive engine','Selected archive','local','Read and capture on this device. A local capture is not approved knowledge.');
    if(!bound)return {root:selected||null,bound,mismatch,unavailable,observedAt:null,nodes,edges,tools,devices,clients,notConnected,receipts,archive,hub:null,pending:null,warning:mismatch?'This archive is not the archive configured for this device’s connectors. Their connections are hidden.':unavailable?'System status is unavailable. The selected local archive remains accessible.':selected?'Local archive open. No matching connector environment has been reported.':'Open or create an archive to see its environment.'};
    function device(name,extra={}){if(!name)return null;const id='device:'+name;let d=devices.find(d=>d.id===id);if(!d){d=node(id,name,'device',{online:null,...extra});devices.push(d);}else Object.assign(d,extra);return d;}
    device(text(machine.host),{local:true,role:machine.role||null,clientMode:machine.client_mode||null});
    for(const h of list(observed.fleet?.hosts)){if(!text(h.host))continue;device(h.host,{online:typeof h.net?.online==='boolean'?h.net.online:null,local:h.host===machine.host,harnesses:list(h.harnesses),registry:h});}
    for(const c of list(observed.clients||hub.clients)){
      if(!text(c.client_id))continue;
      device(c.client_id,{role:'client',clientMode:c.client_mode||null,intake:c});
    }
    const hubConfigured=!!machine.hub_pointer||hub.via==='local'||text(hub.via).startsWith('ssh ');
    let hubNode=null;
    if(hubConfigured){
      const name=text(hub.hub_host)||text(hub.via).replace(/^ssh /,'')||text(machine.hub_pointer).split(':')[0]||'Configured hub';
      hubNode=node('hub',name==='local'?(text(machine.host)||'This device'):name,'hub',{reachable:hub.reachable===true?true:hub.reachable===false?false:null,via:hub.via||null});
      edge('hub-control','app','hub',text(hub.via).startsWith('ssh ')?'SSH':hub.via==='local'?'Local subprocess':'Transport not reported',hub.reachable===true?'Hub answered':hub.reachable===false?'Hub unavailable':'Configured; not verified','control','Status reads and owner decisions share the configured hub. Decisions still require validation and explicit owner action.');
    }
    for(const d of devices.filter(d=>d.intake)){
      const c=d.intake,n=node('intake:'+c.client_id,c.client_id+' intake','intake',{record:c});
      edge('receive:'+c.client_id,d.id,n.id,'Selected contribution',c.received_at?'Received by hub':'Receipt unverified','contribution','Collection time is client reported. Hub receipt confirms transport only.');
      edge('import:'+c.client_id,n.id,'archive','Validated raw import',c.imported_at?'Imported into raw':'Import unverified','contribution','Validated items enter the assigned capture lane. Promotion requires curation and review.');
    }
    const laneNodes=new Map();
    function lane(name){if(!name)return null;if(laneNodes.has(name))return laneNodes.get(name);const record=list(observed.lanes).find(l=>l.lane===name)||{};const n=node('lane:'+name,name,'lane',{record});laneNodes.set(name,n);return n;}
    for(const h of list(observed.harnesses)){
      if(!text(h.id))continue;
      const configuredTool=h.state==='connected'||h.state==='partial'||h.job_loaded===true||h.hook_registered===true||h.hub_installed===true;
      if(!configuredTool){if(h.detected===true)notConnected.push({id:h.id,name:h.name||h.id});continue;}
      const host=text(h.runs_on)||text(machine.host),d=device(host);
      const failed=(h.job?.last_exit!=null&&h.job.last_exit!==0)||/^FAILED\b/.test(text(h.last_status))||/Failed:\s*[1-9]\d*/i.test(text(h.last_run));
      const last=text(h.last_run).match(/\d{4}-\d\d-\d\dT\S+/)?.[0],date=last?Date.parse(last):NaN;
      const runAge=Number.isFinite(h.run_age_h)?h.run_age_h:Number.isFinite(date)?Math.max(0,(Date.now()-date)/3600000):null;
      const late=runAge!=null&&Number.isFinite(h.cadence_s)&&h.cadence_s>0&&runAge*3600>h.cadence_s;
      const canRead=(d?.clientMode||machine.client_mode)!=='contribute-only'&&h.trusted!==false&&h.hook_registered===true&&['hook','instruction'].includes(h.read);
      const collects=h.job_loaded===true&&(h.has_mirror===true||h.hub_installed===true);
      const rawSuffix=text(h.lane_dir).split('/raw/')[1];
      const receipt=receipts.find(r=>r.producer===(rawSuffix||('tools/'+text(h.lane))))||null;
      const t=node('tool:'+h.id,text(h.name)||h.id,'tool',{toolId:h.id,host,deviceId:d?.id,state:h.state||'Setup unknown',read:h.read,canRead,collects,failed,late,runAge,receipt,lane:text(h.lane),trusted:h.trusted,hook:h.hook_registered});tools.push(t);
      if(canRead)edge('read:'+h.id,'archive',t.id,h.read==='hook'?'Session-start hook':'Tool instructions',receipt?(receipt.test?'Test preparation receipt':'Preparation receipt'):'Configured; delivery unverified','read','Only trusted knowledge is selected. Preparation does not prove tool receipt or model use.');
      const l=lane(t.lane);
      if(collects&&l)edge('capture:'+h.id,t.id,l.id,'Connector collection',failed?'Last collection failed':late?'Collection overdue':'Collection configured','capture','Contributes captured material to its declared lane. Success and publication are separate observations.');
    }
    for(const l of list(observed.lanes)){
      if(!text(l.lane)||l.associated===false)continue;const n=lane(l.lane);
      if(l.write==='git-branch'){
        const d=device(text(l.host)||text(l.producer));
        if(d)edge('producer:'+l.lane,d.id,n.id,'Git branch contract','Declared lane; transport endpoint not reported','contribution','Publishes this producer’s lane. This status does not prove its remote URL or that the hub accepted the latest head.');
        const delivery=list(observed.backups?.lanes).find(x=>x.lane===l.lane);
        if(hubNode)edge('accept:'+l.lane,n.id,hubNode.id,'Hub lane integration',delivery?.delivery==='accepted'?'Observed head accepted':delivery?.delivery==='waiting'?'Waiting for acceptance':'Acceptance unverified','contribution','Source publication and hub acceptance are distinct. Use the hub’s acceptance evidence for the observed source head.');
      }
      if(l.vault_age_h!=null)edge('stored:'+l.lane,n.id,'archive','Local lane files','Files observed in selected archive','storage','Presence of raw files does not establish their transport, trust, or completeness.');
    }
    const relay=observed.relay;
    const relayDest=path(relay?.dest),relayBound=relayDest===selected||(relayDest.startsWith(selected+'/')&&!relayDest.split('/').includes('..'));
    if(relay&&relay.enabled!==false&&relayBound){
      const r=node('relay',text(relay.label)||'File relay','relay',{loaded:relay.job_loaded===true});
      for(const [i,s] of list(relay.sources).entries()){if(!text(s.path))continue;const n=node('relay-source:'+i,text(s.name)||text(s.path).split('/').pop(),'staging',{path:s.path,exists:s.exists});edge('relay-source:'+i,n.id,r.id,'Configured file relay',s.exists===true?'Source exists':s.exists===false?'Source missing':'Source unverified','relay','Retain the source permission boundary until an equivalent direct writer has been verified.');}
      edge('relay-destination',r.id,'archive','Configured file relay',relay.last_exit!=null&&relay.last_exit!==0?'Last relay failed':relay.job_loaded===true?'Relay loaded':'Relay not loaded','relay','Destination: '+relayDest+'. This is inside the selected archive. Transport details beyond the relay contract are not reported here.');
    }
    const obsidian=observed.obsidian;
    if(obsidian?.vault_name===archive.name){
      const client=node('client:obsidian','Obsidian','archive client',{sync:text(obsidian.sync)||null});clients.push(client);
      edge('obsidian-access','archive',client.id,'Obsidian vault association',client.sync?'Sync state reported: '+client.sync:'Vault name matched','access','The reported vault name matches this archive. This observation does not establish a remote sync destination or prove another device has received changes.');
    }
    return {root:selected,bound,mismatch:false,unavailable:false,observedAt:observed.generated_at||null,nodes,edges,tools,devices,clients,notConnected,receipts,archive,hub:hubNode,pending:hub.reachable===true&&Number.isInteger(hub.pending)&&hub.pending>=0?hub.pending:null,warning:null};
  }
  const api={build};if(typeof module!=='undefined'&&module.exports)module.exports=api;else scope.SovEnvironment=api;
})(typeof window!=='undefined'?window:{});
