'use strict';
// The home consumes existing status and receipt contracts. It has no write commands.
window.Home = (() => {
  let api, root=null, status=null, context=null, pending=false, request=0, view='overview', selected=null, expanded=false;
  const element=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e};
  const validTime=value=>{const n=Date.parse(value);return Number.isFinite(n)?n:null};
  const ago=value=>{const n=validTime(value);if(n===null)return 'time unknown';const min=Math.max(0,Math.round((Date.now()-n)/60000));return min<60?min+'m ago':min<1440?Math.floor(min/60)+'h ago':Math.floor(min/1440)+'d ago'};
  const operations=(view,id,section)=>api.send({cmd:'navigate',page:'operations',place:{view,...(section?{section}:{}),...(id?{sel:{id}}:{})}});
  function row(title,detail,state,click,action){const e=element(click?'button':'div',null,'home-row');e.append(element('i',null,'health-dot '+(state||'')));const body=element('span',null,'text');body.append(element('strong',title));if(detail)body.append(element('small',detail));e.append(body);if(click){e.append(element('span',action||'›',action?'home-action':'chevron'));e.onclick=click}return e}
  function details(issue){
    const box=element('details',null,'home-issue');box.append(element('summary','Details'));
    for(const key of ['detail','why','action','verify'])if(issue?.[key])box.append(element('p',issue[key]));
    const url=SovStatus.safeURL(issue?.url);if(url){const link=element('a','Open verification link');link.href=url;link.onclick=e=>{e.preventDefault();api.send({cmd:'openurl',url})};box.append(link)}
    if(issue?.action){const copy=element('button','Copy next step');copy.onclick=()=>{api.send({cmd:'copyText',text:issue.action});copy.textContent='Copied'};box.append(copy)}
    return box;
  }
  function observation(host){
    const p=element('p',SovStatus.caption(status),'home-observation');p.setAttribute('role','status');host.append(p);
    if(status?._status?.error)host.append(element('p',status._status.error,'home-banner'));
  }
  function panel(title,count){const p=element('section',null,'home-panel'),h=element('h2',title);if(count!=null)h.append(element('span',String(count)));p.append(h);return p}
  function message(p,text){p.append(element('p',text,'home-message'))}
  function ageFromRun(h){if(h.run_age_h!=null&&Number.isFinite(h.run_age_h))return h.run_age_h;const match=String(h.last_run||'').match(/\d{4}-\d\d-\d\dT\S+/);const n=match&&validTime(match[0]);return n==null?null:Math.max(0,(Date.now()-n)/3600000)}
  // How complete the archive is, above everything else, every time. The hub always
  // reported these numbers and the app showed none of them: a row saying "open Review"
  // while thousands of items sat unread. A bar rather than a sentence because the shape
  // of what is left is the part worth seeing at a glance.
  function coverage(host){
    const c=SovStatus.assess(status||{}).completeness;if(!c)return;
    const box=element('section',null,'home-coverage');
    const head=element('div',null,'coverage-head');
    head.append(element('strong',c.read.pct!=null?c.read.pct+'% read':'Coverage unknown'));
    head.append(element('small',c.headline));
    box.append(head);
    if(c.read.total>0){
      const bar=element('div',null,'coverage-bar');
      const seg=(cls,n)=>{if(!n)return;const s=element('i',null,'coverage-seg '+cls);s.style.flexGrow=String(n);bar.append(s)};
      // read, still to read, and the tail the nightly will never reach: three different
      // kinds of incomplete, so they are three segments rather than one number.
      seg('read',c.read.judged);seg('waiting',c.waiting);seg('unreachable',c.out_of_reach);
      box.append(bar);
      const legend=element('p',null,'coverage-legend');
      legend.append(element('span',c.detail));
      if(c.waiting)legend.append(element('span',' · '+c.waiting.toLocaleString()+' waiting'));
      if(c.out_of_reach)legend.append(element('span',' · '+c.out_of_reach.toLocaleString()+' out of reach'));
      box.append(legend);
    } else box.append(element('p',c.detail,'coverage-legend'));
    host.append(box);
  }
  function render(){
    if(!api)return;const host=document.getElementById('system-home');host.replaceChildren();host.classList.toggle('system-mode',view==='system');
    if(view==='system'){
      const lead=element('div',null,'home-lead'),intro=element('div');intro.append(element('h1','System'));
      const refresh=element('button',pending?'Checking…':'Refresh status');refresh.disabled=pending;refresh.onclick=()=>Home.refresh();lead.append(intro,refresh);host.append(lead);
      const badge=document.getElementById('review-count');if(badge)badge.textContent=GateModel.queue(status,root).count||'';
      observation(host);if(!status?.machine&&!status?.error)return;
      const environment=element('div');host.append(environment);SystemView.render(environment,{root,status,context},{browse:api.browse,review:api.review,openNote:api.openNote,operations});return;
    }
    const lead=element('div',null,'home-lead'),intro=element('div');intro.append(element('h1','Your system'));
    const machine=status?.machine||{},hub=status?.hub||{};
    intro.append(element('p',status?.error?'System status unavailable. Your local archive is still available.':machine.connected?`${machine.vault_name||'Connected archive'} · ${machine.host||'this device'}`:'Open an archive and see which tools are connected.'));
    const refresh=element('button',pending?'Checking…':'Refresh status');refresh.disabled=pending;refresh.onclick=()=>Home.refresh();lead.append(intro,refresh);host.append(lead);
    observation(host);if(!status?.machine&&!status?.error)return;
    coverage(host);
    if(machine.role){const mode=machine.client_mode==='contribute-only'?'Contribute only':machine.client_mode==='read-and-contribute'?'Read and contribute':machine.role==='client'?'Mode not declared':'';host.append(element('p',(machine.host||'This machine')+' · '+(machine.role==='hub'?'Hub':'Client')+(mode?' / '+mode:''),'home-subhead'))}
    if(root&&machine.vault&&root!==machine.vault)host.append(element('div',`You are browsing ${root.split('/').pop()}. Connections below belong to ${machine.vault_name||'another archive'} (${machine.vault}). Opening an archive does not connect it to these tools.`,'home-banner'));
    if(status?.error)host.append(element('div',status.error,'home-banner'));
    const badge=document.getElementById('review-count');if(badge)badge.textContent=GateModel.queue(status,root).count||'';
    if(!root&&!machine.connected&&!status?.error)return;
    const grid=element('div',null,'home-grid');host.append(grid);
    const nodes=status?.fleet?.hosts||[],tools=(status?.harnesses||[]).filter(h=>h.detected||h.state==='connected'||h.state==='partial'||h.runs_on||h.hub_installed);
    const assessment=SovStatus.assess(status||{},localStorage),needs=assessment.need,deliveries=status?.backups?.lanes||[];
    const attention=panel('Needs your attention',needs.length||null);
    for(const need of needs){
      const source=need.need!=null?status.needs_you[need.need]:null;
      const gate=source?.kind==='gate';
      const cause=need.cause||need.group;
      const title=gate?`${hub.pending||'New'} proposals`:cause==='job-failed'?`${need.name} failed`:cause==='no-backup'?`${need.name}: no backup recorded`:need.name;
      const groupViews=[...new Set((need.members||[]).map(member=>member.jump?.view))];
      const jump=need.jump||(groupViews.length===1&&groupViews[0]?{view:groupViews[0]}:null)||{view:source?.harness?'tools':source?.kind==='job'?'jobs':'glance',id:source?.harness};
      const action=gate?'Review':jump.view==='jobs'?(jump.id?'View job':'View jobs'):jump.view==='backups'?'View backups':jump.view==='hosts'?(jump.id?'View device':'View devices'):jump.view==='tools'?'View tools':'Open details';
      attention.append(row(title,gate||['job-failed','no-backup'].includes(cause)?'':need.detail,need.state,()=>gate?api.review():operations(jump.view,jump.id),action));
      if(!gate)attention.append(details(need));
    }
    if(!needs.length)message(attention,!status||status.error?'Waiting for a successful status check.':hub.reachable===true?'No attention items reported by the connected system.':'No local attention items reported. Hub review status is unverified.');

    if(assessment.waiting.length){
      const watching=panel('Awaiting verification',assessment.waiting.length);watching.classList.add('home-waiting');
      for(const issue of assessment.waiting){watching.append(row(issue.name,issue.detail,'',()=>operations(issue.jump.view,issue.jump.id),'View job'));watching.append(details(issue))}
      grid.append(watching);
    }
    const clients=status?.clients||hub.clients||[];
    const incoming=panel('Contributions',(deliveries.length+clients.length)||null);
    for(const c of clients){const record=element('div',null,'home-intake');record.append(element('h3',c.client_id+' · Client / Contribute only'));for(const [label,value] of [['Collection (client reported)',c.collected_at],['Received by hub',c.received_at],['Imported into raw',c.imported_at]]){const stage=element('div',label,'home-stage');stage.append(element('small',value?ago(value):'Not reported'));record.append(stage)}record.append(element('p',c.state==='error'||c.state==='rejected'?'Intake needs attention: '+(c.reason||'See rejected items in the hub receipt.'):'Intake: '+(c.state||'not reported')+'. Promotion requires curation and review.'));incoming.append(record)}
    for(const lane of deliveries){const accepted=lane.delivery==='accepted';incoming.append(row(lane.lane,accepted?'Accepted by the hub · source '+ago(lane.pushed):lane.delivery==='waiting'?'Published · waiting for hub acceptance':SovStatus.contributionIssue(lane).text,accepted?'live':lane.delivery==='waiting'?'warn':'idle',()=>operations('backups','bk:lane:'+lane.lane)));if(!accepted&&lane.delivery!=='waiting')incoming.append(details(SovStatus.contributionIssue(lane)))}
    if(!deliveries.length&&!clients.length)message(incoming,hub.reachable===true?'No contribution acceptance records were returned.':'Check the hub to verify which contributions have been accepted.');
    attention.classList.add('home-attention');incoming.classList.add('home-contributions');
    const connections=panel('Nodes',nodes.length||null);connections.classList.add('home-nodes');
    for(const n of (expanded?nodes:nodes.slice(0,4))){const state=n.net?.online===true?'live':n.net?.online===false?'down':'';const label=state==='live'?'Reachable':state==='down'?'Unreachable':'Reachability unknown';const count=(n.harnesses||[]).length;connections.append(row(n.host,`${label} · ${count} producer${count===1?'':'s'}`,state,()=>operations('hosts',n.host)))}
    if(nodes.length>4){const toggle=element('button',expanded?'Show fewer nodes':'Show all '+nodes.length+' nodes','home-node-toggle');toggle.onclick=()=>{expanded=!expanded;render()};connections.append(toggle)}
    if(!nodes.length)message(connections,'No nodes reported. A local archive can be used independently.');grid.append(connections);
    const producers=panel('Tools & producers',tools.length||null);producers.classList.add('home-tools');
    for(const t of tools){const ah=ageFromRun(t),cad=(t.cadence_s||900)/3600,failed=(t.job?.last_exit!=null&&t.job.last_exit!==0)||/^FAILED\b/.test(String(t.last_status||''))||/Failed:\s*[1-9]\d*/i.test(String(t.last_run||''));const health=failed?'down':ah!=null&&ah>cad?'warn':ah!=null?'live':'';
      const prepared=root===machine.vault?(context?.receipts||[]).find(r=>r.producer.split('/').pop()===t.lane):null;
      const read=t.read==='none'?'Collection only':t.trusted===false?'Context access not trusted':t.hook_registered===true?(t.read==='instruction'?'Context instructions configured':'Context hook configured'):'Context setup unverified';
      const item=row(t.name||t.id,`${t.state||'Setup unknown'}${t.runs_on?' on '+t.runs_on:''} · ${read}\n${failed?'Last collection failed':ah==null?'Collection time unknown':'Collection '+(ah<1?Math.round(ah*60)+'m':Math.floor(ah)+'h')+' ago'}${prepared?' · '+prepared.topic+' prepared '+ago(prepared.prepared_at):''}`,health,()=>{selected=t.id;render()});item.setAttribute('aria-pressed',String(selected===t.id));producers.append(item)}
    if(!tools.length)message(producers,'No connected tools reported. Existing connector setup is available in Operations.');grid.prepend(connections,producers);
    const tool=tools.find(t=>t.id===selected),allReceipts=context?.receipts||[];
    const receipts=tool?(root===machine.vault&&tool.lane?allReceipts.filter(r=>r.producer.split('/').pop()===tool.lane):[]):allReceipts;
    const packs=panel(tool?'Context / '+(tool.name||tool.id):'Context prepared',tool?receipts.length:context?.total);packs.classList.add('home-packs');
    if(tool){const b=element('button','Tool details');b.onclick=()=>operations('tools',tool.id);packs.append(b);const all=element('button','All context');all.onclick=()=>{selected=null;render()};packs.append(all)}
    for(const [title,sub] of [['Preparation',receipts.length?'Receipts available below':'No matching receipt'],['Delivery unconfirmed','No receipt from the consuming tool'],['Loading unconfirmed','No model-session acknowledgement']]){const stage=element('div',title,'home-stage');stage.append(element('small',sub));packs.append(stage)}
    message(packs,'Receipts establish preparation only. Delivery to the tool and loading into a model are unverified.');
    if(root)packs.append(element('div',`${root.split('/').pop()} · ${context?.observed_at?'receipts checked '+ago(context.observed_at):'checking receipts…'}`,'home-subhead'));
    const list=element('div',null,'home-context');
    for(const r of receipts)list.append(row(r.topic,`${r.producer} · ${r.cards} cards · ${ago(r.prepared_at)}${r.test?' · test receipt':''}`,null,()=>api.openNote(r.path)));
    packs.append(list);if(!receipts.length)message(packs,context?.error||(!root?'Open an archive to inspect its context receipts.':'No readable preparation receipts in this archive. Delivery and loading remain unverified.'));
    if(context?.skipped)message(packs,`${context.skipped} receipt file(s) could not be read safely.`);if(context?.limited)message(packs,'Showing the latest 100 producer receipts.');grid.append(packs,incoming);grid.prepend(attention);const waitingPanel=grid.querySelector(".home-waiting");if(waitingPanel)attention.after(waitingPanel);
    if(root){const local=element('div',null,'home-local');local.append(element('span','Your notes remain plain Markdown.'));const b=element('button','Browse & inspect');b.onclick=api.browse;local.append(b);host.append(local)}
  }
  return {init(options){api=options;render()},view(value){view=value;render()},archive(value){root=value;context=null;selected=null;render()},context(value){context=value;render()},status(value){if(value.request!==request)return;pending=value._status?.pending===true;status=SovStatus.retain(status,value);render()},refresh(){if(pending)return;pending=true;if(status)status={...status,_status:{...status._status,pending:true,stale:true}};render();api.send({cmd:'status',request:++request})}};
})();
