'use strict';
// The home consumes existing status and receipt contracts. It has no write commands.
window.Home = (() => {
  let api, root=null, status=null, context=null, pending=false, timeout, request=0, view='overview', selected=null, expanded=false;
  const element=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e};
  const validTime=value=>{const n=Date.parse(value);return Number.isFinite(n)?n:null};
  const ago=value=>{const n=validTime(value);if(n===null)return 'time unknown';const min=Math.max(0,Math.round((Date.now()-n)/60000));return min<60?min+'m ago':min<1440?Math.floor(min/60)+'h ago':Math.floor(min/1440)+'d ago'};
  const operations=(view,id,section)=>api.send({cmd:'navigate',page:'operations',place:{view,...(section?{section}:{}),...(id?{sel:{id}}:{})}});
  function row(title,detail,state,click){const e=element(click?'button':'div',null,'home-row');e.append(element('i',null,'health-dot '+(state||'')));const body=element('span',null,'text');body.append(element('strong',title),element('small',detail));e.append(body);if(click){e.append(element('span','›','chevron'));e.onclick=click}return e}
  function panel(title,count){const p=element('section',null,'home-panel'),h=element('h2',title);if(count!=null)h.append(element('span',String(count)));p.append(h);return p}
  function message(p,text){p.append(element('p',text,'home-message'))}
  function ageFromRun(h){if(h.run_age_h!=null&&Number.isFinite(h.run_age_h))return h.run_age_h;const match=String(h.last_run||'').match(/\d{4}-\d\d-\d\dT\S+/);const n=match&&validTime(match[0]);return n==null?null:Math.max(0,(Date.now()-n)/3600000)}
  function render(){
    if(!api)return;const host=document.getElementById('system-home');host.replaceChildren();
    const lead=element('div',null,'home-lead'),intro=element('div');intro.append(element('h1',view==='review'?'Review':'Your system'));
    const machine=status?.machine||{},hub=status?.hub||{};
    intro.append(element('p',status?.error?'System status unavailable. Your local archive is still available.':machine.connected?`${machine.vault_name||'Connected archive'} · ${machine.host||'this device'} · observed ${ago(status.generated_at)}`:'Open an archive and see which tools are connected.'));
    const refresh=element('button',pending?'Checking…':'Refresh status');refresh.disabled=pending;refresh.onclick=()=>Home.refresh();lead.append(intro,refresh);host.append(lead);
    if(root&&machine.vault&&root!==machine.vault)host.append(element('div',`You are browsing ${root.split('/').pop()}. Connections below belong to ${machine.vault_name||'another archive'} (${machine.vault}). Opening an archive does not connect it to these tools.`,'home-banner'));
    if(status?.error)host.append(element('div',status.error,'home-banner'));
    const badge=document.getElementById('review-count');if(badge)badge.textContent='';
    if(!root&&!machine.connected&&!status?.error)return;
    const grid=element('div',null,'home-grid');host.append(grid);
    const nodes=status?.fleet?.hosts||[],tools=(status?.harnesses||[]).filter(h=>h.detected||h.state==='connected'||h.state==='partial'||h.runs_on||h.hub_installed);
    const needs=(status?.needs_you||[]).map(n=>n.kind==='gate'?{...n,view:'archive',section:'gate',text:`${hub.pending||'New'} proposals ready for your review`}:n),deliveries=status?.backups?.lanes||[];
    for(const lane of deliveries)if(lane.delivery!=='accepted')needs.push({text:`${lane.lane}: ${lane.delivery==='waiting'?'contribution waiting for hub acceptance':'contribution acceptance unverified'}`,view:'backups',id:'bk:lane:'+lane.lane});
    if(hub.reachable===false)needs.unshift({text:'Hub unreachable. Review and contribution acceptance could not be checked.',view:'jobs'});
    const attention=panel('Needs your attention',needs.length||null);
    for(const need of needs)attention.append(row(need.text||need.kind||'Review needed','Open details','warn',()=>operations(need.view||(need.kind==='gate'?'jobs':'glance'),need.id,need.section)));
    if(!needs.length)message(attention,!status||status.error?'Waiting for a successful status check.':hub.reachable===true?'No attention items reported by the connected system.':'No local attention items reported. Hub review status is unverified.');
    if(badge)badge.textContent=needs.length?String(needs.length):'';
    const incoming=panel('Contributions',deliveries.length||null);
    for(const lane of deliveries){const accepted=lane.delivery==='accepted';incoming.append(row(lane.lane,accepted?'Accepted by the hub · source '+ago(lane.pushed):lane.delivery==='waiting'?'Published · waiting for hub acceptance':'Acceptance unverified',accepted?'live':'warn',()=>operations('backups','bk:lane:'+lane.lane)))}
    if(!deliveries.length)message(incoming,hub.reachable===true?'No contribution acceptance records were returned.':'Check the hub to verify which contributions have been accepted.');
    if(view==='review'){grid.classList.add('home-review');grid.append(attention,incoming);return}
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
    if(context?.skipped)message(packs,`${context.skipped} receipt file(s) could not be read safely.`);if(context?.limited)message(packs,'Showing the latest 100 producer receipts.');grid.append(packs);
    if(root){const local=element('div',null,'home-local');local.append(element('span','Your notes remain plain Markdown.'));const b=element('button','Browse & inspect');b.onclick=api.browse;local.append(b);host.append(local)}
  }
  return {init(options){api=options;render()},view(value){view=value;render()},archive(value){root=value;context=null;selected=null;render()},context(value){context=value;render()},status(value){if(value.request!==request)return;clearTimeout(timeout);pending=false;status=value;render()},refresh(){if(pending)return;pending=true;render();api.send({cmd:'status',request:++request});timeout=setTimeout(()=>{pending=false;request++;status={error:'The status check timed out. Retry to get a current observation.'};render()},45000)}};
})();
