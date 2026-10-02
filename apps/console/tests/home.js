(() => {
 const failures=[], checks=[];
 const assert=(name,ok)=>{checks.push(name);if(!ok)failures.push(name)};
 const $=id=>document.getElementById(id);
 const home=()=>$('system-home'),text=()=>home().textContent;
 try {
   assert('starts on Today', !home().hidden&&$('today-tab').getAttribute('aria-pressed')==='true'&&$('page-label').textContent==='Today');
   assert('Notes UI removed',!$('notes-tab')&&!$('workspace')&&!window.sovNewCapture);
   Home.status({request:1,generated_at:new Date().toISOString(),machine:{connected:true,vault:root,vault_name:'QA archive',host:'test'},hub:{reachable:true,pending:2,proposals:[{slug:'first'},{slug:'second'}]},needs_you:[{kind:'gate',text:'internal command text'}],fleet:{hosts:[{host:'<img src=x onerror=alert(1)>',net:{online:false},harnesses:[]}]},harnesses:[{id:'codex',name:'Codex',state:'connected',read:'hook',hook_registered:true,detected:true,last_status:'FAILED collection test',job:{last_exit:0}}],archive:{total:12,cards:[]},backups:{lanes:[{lane:'waiting-producer',delivery:'waiting'},{lane:'unknown-producer'},{lane:'accepted-producer',delivery:'accepted'}]}});
   assert('source labels cannot inject HTML',!home().querySelector('img')&&text().includes('<img'));
   assert('one headline counts what needs the owner',home().querySelector('.today-headline h2').textContent==='3 things need you');
   assert('review count is in the navigation',$('review-count').textContent==='2');
   const rows=[...home().querySelectorAll('.today-needs .today-item')];
   assert('gate uses user-facing language',rows.some(r=>r.textContent.includes('2 proposals')&&r.textContent.includes('Review'))&&!text().includes('internal command text'));
   assert('waiting is not accepted',rows.some(r=>r.textContent.includes('waiting-producer')&&r.textContent.includes('awaiting hub')));
   assert('unknown acceptance is not attention',!text().includes('unknown-producer'));
   assert('a row is a name and a short reason',rows.every(r=>r.querySelector('.today-row').getBoundingClientRect().height<=48));
   const lane=rows.find(r=>r.textContent.includes('waiting-producer'));
   assert('the sentence is closed until asked for',lane.querySelector('.today-detail').hidden);
   lane.querySelector('.today-main').click();
   const opened=[...home().querySelectorAll('.today-item')].find(r=>r.textContent.includes('waiting-producer'));
   assert('the sentence opens under its row',!opened.querySelector('.today-detail').hidden&&opened.querySelector('.today-detail p').getBoundingClientRect().height>0);
   assert('guidance can be copied from the detail',[...opened.querySelectorAll('.today-detail button')].some(b=>b.textContent==='Copy next step'));
   assert('four figures follow',home().querySelectorAll('.today-tiles .fig-tile').length===4&&home().querySelector('.today-tiles').textContent.includes('12'));
   assert('status timing is not page content',!text().includes('Status took')&&!text().includes('Observed'));
   Home.status({request:999,error:'LATE_RESPONSE_SENTINEL'});
   assert('late responses ignored',!text().includes('LATE_RESPONSE_SENTINEL'));
   Home.archive('/some/other/archive');
   assert('archive mismatch is visible',text().includes('Opening an archive does not connect it'));
   Home.archive(root);
   assert('no page-level horizontal overflow',document.documentElement.scrollWidth<=document.documentElement.clientWidth);
   finish();
 } catch(e){failures.push(String(e.stack||e));finish()}
 function finish(){window.webkit.messageHandlers.sov.postMessage({cmd:'clientError',where:'native-qa',msg:JSON.stringify({checks,failures})})}
})();
