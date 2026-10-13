'use strict';
// Today answers one question: what needs me. Each thing is said once, as a name, a
// short reason and where to go; the sentence that explains it opens under its row.
// The only command it sends is the app's own update. Everything else is a jump.
window.Home = (() => {
  let api, root=null, status=null, context=null, pending=false, request=0, view='overview', open=null;
  const element=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e};
  const num=n=>Number(n).toLocaleString();
  const plural=(n,word)=>n+' '+word+(n===1?'':'s');
  // Jumps handed out by the status service and the shared assessment still use the
  // names of the views these destinations replaced.
  const PLACE={tools:'sources',lanes:'sources',glance:'sources'};
  // A row's action names where it lands, in one word.
  const DEST={jobs:'Jobs',backups:'Backups',recovery:'Backups',hosts:'Sources',sources:'Sources',tools:'Sources',lanes:'Sources',system:'Sources',archive:'Library'};
  // The Map is a face of Sources that lives in this document.
  const go=(view,id,section)=>view==='system'?api.map():api.elsewhere({view:PLACE[view]||view,...(section?{section}:{}),...(id?{sel:{id}}:{})});
  // Run a row's own action. The app cannot build from its own bundle, so an update hands
  // over this machine's source location; the updater refuses rather than guessing.
  function act(kind){
    if(kind!=='app-update')return;
    const template=status?.machine?.template;
    if(!template){api.send({cmd:'clientError',error:"This device's source location is not known, so there is nothing to build from."});return}
    api.send({cmd:'appUpdate',template});
  }
  // The one place a sentence is allowed: what happened, why, what to do, how to tell it worked.
  function detail(issue){
    const box=element('div',null,'today-detail');
    for(const key of ['detail','why','action','verify'])if(issue?.[key])box.append(element('p',issue[key]));
    for(const member of issue?.members||[issue])if(member?.failure_output){
      box.append(element('strong',member.name||'Captured output'));
      const output=element('pre',member.failure_output);output.style.whiteSpace='pre-wrap';output.style.overflowWrap='anywhere';box.append(output);
    }
    const url=SovStatus.safeURL(issue?.url);if(url){const link=element('a','Open verification link');link.href=url;link.onclick=e=>{e.preventDefault();api.send({cmd:'openurl',url})};box.append(link)}
    if(issue?.action&&!issue.actionKind){const copy=element('button','Copy next step');copy.onclick=()=>{api.send({cmd:'copyText',text:issue.action});copy.textContent='Copied'};box.append(copy)}
    return box.childNodes.length?box:null;
  }
  function headline(host,state,text){
    const h=element('div',null,'today-headline');h.setAttribute('role','status');
    h.append(element('i',null,'health-dot '+state),element('h2',text));host.append(h);
  }
  function item(key,state,title,reason,label,run,body){
    const wrap=element('div',null,'today-item'),row=element('div',null,'today-row'),main=element('button',null,'today-main');
    main.append(element('i',null,'health-dot '+(state||'')),element('strong',title));
    if(reason)main.append(element('span',reason,'reason'));
    const jump=element('button',label+' →','today-go');jump.onclick=run;
    row.append(main,jump);wrap.append(row);
    if(body){
      body.hidden=open!==key;main.setAttribute('aria-expanded',String(open===key));
      main.onclick=()=>{open=open===key?null:key;render()};wrap.append(body);
    }else main.onclick=run;
    return wrap;
  }
  function tile(view,label,figure,unit,note,section){
    const t=element('button',null,'fig-tile');t.append(element('span',label,'cap'));
    const f=element('span',figure,'fig');if(unit)f.append(element('small',unit));
    t.append(f,element('span',note,'fig-note'));t.onclick=()=>go(view,null,section);return t;
  }
  // A young archive's first loop, ticked from evidence only: the tool is connected to this
  // archive, a card has passed the owner's gate, and a real session received cards (its hook
  // receipt says so). Gone once all three hold, so an established archive never sees it.
  function firstSteps(host){
    const machine=status?.machine||{},cards=(status?.archive||{}).total||0,waiting=GateModel.queue(status,root).count||0;
    const connected=!!machine.connected&&(!root||!machine.vault||machine.vault===root);
    const used=(context?.receipts||[]).some(r=>!r.test&&((r.slugs||[]).length||Number(r.cards)>0));
    if(!root||(connected&&cards>0&&used))return false;
    host.append(element('div','First steps','cap today-cap'));
    const list=element('div',null,'plain-list today-first');
    const step=(key,done,title,reason,label,run)=>list.append(item('first:'+key,done?'live':'',title,done?'done':reason,label,run,null));
    step('connect',connected,'Connect Claude Code','so its sessions can read this archive','Sources',()=>go('sources'));
    step('card',cards>0,'Approve your first card',waiting?plural(waiting,'card')+' waiting':'turn on the curator, then save something',
      waiting?'Review':'Settings',()=>waiting?api.review():api.elsewhere({settings:true}));
    step('used',used,'Open a new Claude Code session','it loads your cards, and this ticks','Sources',()=>go('sources'));
    host.append(list);return true;
  }
  function today(host){
    const machine=status?.machine||{},hub=status?.hub||{};
    if(!status||(!status.machine&&!status.error)){headline(host,'','Checking…');host.append(element('p',SovStatus.caption(status),'home-message'));return}
    if(status.error){headline(host,'down','Status unavailable');host.append(element('div',status.error+' Your local archive is still available.','home-banner'));return}
    if(status._status?.error)host.append(element('div',status._status.error,'home-banner'));
    if(root&&machine.vault&&root!==machine.vault)host.append(element('div',`You opened ${root.split('/').pop()}. What is shown here belongs to ${machine.vault_name||'another archive'} (${machine.vault}). Opening an archive does not connect it.`,'home-banner'));
    if(!machine.connected){
      headline(host,'','Not connected');
      if(firstSteps(host))return;
      const connect=element('button','Connect tools');connect.onclick=()=>go('sources');host.append(connect);return;
    }
    const assessment=SovStatus.assess(status,localStorage),needs=assessment.need,count=needs.length,top=SovStatus.headline(status,assessment);
    headline(host,top.state,top.text);
    firstSteps(host);
    if(count){
      const list=element('div',null,'plain-list today-needs');
      for(const need of needs){
        const source=need.need!=null?status.needs_you[need.need]:null,gate=source?.kind==='gate';
        const groupViews=[...new Set((need.members||[]).map(member=>member.jump?.view))];
        const jump=need.jump||(groupViews.length===1&&groupViews[0]?{view:groupViews[0]}:null)||{view:'sources'};
        if(gate)list.append(item('gate',need.state,plural(hub.pending||0,'proposal'),'waiting','Review',()=>api.review(),null));
        // A row that can do the thing says so on the row; nobody should go looking for a button.
        else if(need.actionKind)list.append(item(need.cause||need.name,need.state,need.name,SovStatus.brief(need),need.action||'Do it',()=>act(need.actionKind),detail(need)));
        else list.append(item((need.cause||'')+':'+need.name+':'+(need.need??''),need.state,need.name,SovStatus.brief(need)||need.detail,DEST[jump.view]||'Open',()=>go(jump.view,jump.id),detail(need)));
      }
      host.append(list);
    }
    // What the system is working on by itself. The reading queue has its own figure below.
    const watching=assessment.waiting;
    if(watching.length){
      host.append(element('div','Watching','cap today-cap'));
      const list=element('div',null,'plain-list today-waiting');
      for(const w of watching)list.append(item('w:'+w.name,'',w.name,SovStatus.brief(w)||w.detail,DEST[w.jump.view]||'Open',()=>go(w.jump.view,w.jump.id),detail(w)));
      host.append(list);
    }
    const a=status.archive||{},c=assessment.completeness,bk=status.backups||{},tiles=element('div',null,'tiles4 today-tiles');
    const added=(a.cards||[]).filter(card=>card.week===SovStatus.week(new Date())).length;
    tiles.append(tile('archive','Cards',a.total!=null?num(a.total):'–','',a.total!=null?'+'+added+' this week':'not reported'));
    tiles.append(tile('archive','Read',c.read.pct!=null?String(c.read.pct):'–',c.read.pct!=null?'%':'',c.waiting?num(c.waiting)+' waiting':c.read.total?'nothing waiting':'not reported','judge'));
    const quiet=c.producers.total-c.producers.delivering;
    tiles.append(tile('sources','Sources',c.producers.total?String(c.producers.delivering):'–',c.producers.total?' of '+c.producers.total:'',c.producers.total?(quiet?quiet+' quiet':'all delivering'):'none yet'));
    const snap=bk.snapshots?.newest_age_h,behind=(bk.remotes||[]).filter(r=>r.ahead>0).length;
    const [n,unit]=snap==null?['–','']:snap<1?[String(Math.max(1,Math.round(snap*60))),'m ago']:snap<48?[String(Math.round(snap)),'h ago']:[String(Math.round(snap/24)),'d ago'];
    tiles.append(tile('backups','Backup',n,unit,(bk.remotes||[]).length?(behind?(behind===1?'1 copy':behind+' copies')+' behind':'copies current'):'not reported'));
    host.append(tiles);
  }
  // A refresh redraws the page under the owner every minute, so what they are in the middle of is
  // carried across: the focused control, found again by what it is and which of those it was, gets
  // focus and caret back, and a disclosure they opened stays open.
  const FOCUSABLE='button,input,select,textarea,a,[tabindex]';
  const sig=e=>e.tagName+'|'+(e.dataset?.node||e.dataset?.pane||e.dataset?.route||e.getAttribute('aria-label')||e.textContent.trim().slice(0,80))+'|'+(e.closest('.today-item')?.querySelector('strong')?.textContent||'');
  function keep(host){
    const a=document.activeElement,mine=a&&a!==host&&host.contains(a)?sig(a):null;
    const at=mine&&[...host.querySelectorAll(FOCUSABLE)].filter(e=>sig(e)===mine).indexOf(a),caret=mine&&[a.selectionStart,a.selectionEnd];
    const open=[...host.querySelectorAll('details[open] > summary')].map(x=>x.textContent);
    return ()=>{
      for(const d of host.querySelectorAll('details'))if(open.includes(d.querySelector('summary')?.textContent))d.open=true;
      const f=mine&&[...host.querySelectorAll(FOCUSABLE)].filter(e=>sig(e)===mine)[at];if(!f)return;
      f.focus({preventScroll:true});try{if(caret[0]!=null)f.setSelectionRange(caret[0],caret[1])}catch(e){}
    };
  }
  function render(){
    if(!api)return;const host=document.getElementById('system-home'),restore=keep(host);draw(host);restore();
  }
  function draw(host){
    host.replaceChildren();host.classList.toggle('system-mode',view==='system');
    api.chrome({view,pending,status});
    const badge=document.getElementById('review-count');if(badge)badge.textContent=GateModel.queue(status,root).count||'';
    if(view!=='system')return today(host);
    if(!status?.machine&&!status?.error){host.append(element('p','Checking…','home-message'));return}
    if(status._status?.error)host.append(element('div',status._status.error,'home-banner'));
    const environment=element('div');host.append(environment);
    SystemView.render(environment,{root,status,context},{browse:api.browse,review:api.review,openNote:api.openNote,operations:go});
  }
  return {init(options){api=options;render()},view(value){view=value;render()},archive(value){root=value;context=null;open=null;render()},context(value){context=value;render()},status(value){if(value.request!==request)return;pending=value._status?.pending===true;status=SovStatus.retain(status,value);render();api.send({cmd:'verdict',...SovStatus.verdict(status,localStorage)})},refresh(){if(pending)return;pending=true;if(status)status={...status,_status:{...status._status,pending:true,stale:true}};render();api.send({cmd:'status',request:++request})}};
})();
