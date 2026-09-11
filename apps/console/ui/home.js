'use strict';
// The home consumes existing status and receipt contracts. It has no write commands.
window.Home = (() => {
  let api, root=null, status=null, context=null, pending=false, request=0, view='overview', selected=null, expanded=false;
  const element=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e};
  const validTime=value=>{const n=Date.parse(value);return Number.isFinite(n)?n:null};
  const ago=value=>{const n=validTime(value);if(n===null)return 'time unknown';const min=Math.max(0,Math.round((Date.now()-n)/60000));return min<60?min+'m ago':min<1440?Math.floor(min/60)+'h ago':Math.floor(min/1440)+'d ago'};
  const operations=(view,id,section)=>api.send({cmd:'navigate',page:'operations',place:{view,...(section?{section}:{}),...(id?{sel:{id}}:{})}});
  function row(title,detail,state,click){const e=element(click?'button':'div',null,'home-row');e.append(element('i',null,'health-dot '+(state||'')));const body=element('span',null,'text');body.append(element('strong',title),element('small',detail));e.append(body);if(click){e.append(element('span','›','chevron'));e.onclick=click}return e}
  function details(issue){
    const box=element('div',null,'home-issue');
    for(const[key,label]of[['why','Why'],['action','Next step'],['verify','Confirm']])if(issue?.[key]){const p=element('p');p.append(element('strong',label+': '),document.createTextNode(issue[key]));box.append(p)}
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
    if(root&&machine.vault&&root!==machine.vault)host.append(element('div',`You are browsing ${root.split('/').pop()}. Connections below belong to ${machine.vault_name||'another archive'} (${machine.vault}). Opening an archive does not connect it to these tools.`,'home-banner'));
    if(status?.error)host.append(element('div',status.error,'home-banner'));
    const badge=document.getElementById('review-count');if(badge)badge.textContent=GateModel.queue(status,root).count||'';
    if(!root&&!machine.connected&&!status?.error)return;
    const grid=element('div',null,'home-grid');host.append(grid);
    const nodes=status?.fleet?.hosts||[],tools=(status?.harnesses||[]).filter(h=>h.detected||h.state==='connected'||h.state==='partial'||h.runs_on||h.hub_installed);
    const needs=SovStatus.assess(status||{},localStorage).need,deliveries=status?.backups?.lanes||[];
    const attention=panel('Needs your attention',needs.length||null);
    for(const need of needs){
      const source=need.need!=null?status.needs_you[need.need]:null;
      const gate=source?.kind==='gate';
      const title=gate?`${hub.pending||'New'} proposals ready for your review`:need.name;
      const jump=need.jump||{view:source?.harness?'tools':source?.kind==='job'?'jobs':'glance',id:source?.harness};
      attention.append(row(title,gate?'Review proposals':need.detail,need.state,()=>gate?api.review():operations(jump.view,jump.id)),details(source||need));
    }
    if(!needs.length)message(attention,!status||status.error?'Waiting for a successful status check.':hub.reachable===true?'No attention items reported by the connected system.':'No local attention items reported. Hub review status is unverified.');

    const incoming=panel('Contributions',deliveries.length||null);
    for(const lane of deliveries){const accepted=lane.delivery==='accepted';incoming.append(row(lane.lane,accepted?'Accepted by the hub · source '+ago(lane.pushed):lane.delivery==='waiting'?'Published · waiting for hub acceptance':SovStatus.contributionIssue(lane).text,accepted?'live':lane.delivery==='waiting'?'warn':'idle',()=>operations('backups','bk:lane:'+lane.lane)));if(!accepted&&lane.delivery!=='waiting')incoming.append(details(SovStatus.contributionIssue(lane)))}
    if(!deliveries.length)message(incoming,hub.reachable===true?'No contribution acceptance records were returned.':'Check the hub to verify which contributions have been accepted.');
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
    if(context?.skipped)message(packs,`${context.skipped} receipt file(s) could not be read safely.`);if(context?.limited)message(packs,'Showing the latest 100 producer receipts.');grid.append(packs,incoming);grid.prepend(attention);
    if(root){const local=element('div',null,'home-local');local.append(element('span','Your notes remain plain Markdown.'));const b=element('button','Browse & inspect');b.onclick=api.browse;local.append(b);host.append(local)}
  }
  return {init(options){api=options;render()},view(value){view=value;render()},archive(value){root=value;context=null;selected=null;render()},context(value){context=value;render()},status(value){if(value.request!==request)return;pending=value._status?.pending===true;status=SovStatus.retain(status,value);render()},refresh(){if(pending)return;pending=true;if(status)status={...status,_status:{...status._status,pending:true,stale:true}};render();api.send({cmd:'status',request:++request})}};
})();
