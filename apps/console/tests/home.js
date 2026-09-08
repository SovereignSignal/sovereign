(() => {
 const failures=[], checks=[];
 const assert=(name,ok)=>{checks.push(name);if(!ok)failures.push(name)};
 const $=id=>document.getElementById(id);
 const originalConfirm=window.confirm;
 try {
   assert('starts on unified home', !$('system-home').hidden && $('workspace').hidden);
   assert('notes available for selected archive', !$('notes-tab').disabled);
   Home.status({request:1,generated_at:new Date().toISOString(),machine:{connected:true,vault:root,vault_name:'QA archive',host:'test'},hub:{reachable:true,pending:2},needs_you:[{kind:'gate',text:'internal command text'}],fleet:{hosts:[{host:'<img src=x onerror=alert(1)>',net:{online:true},harnesses:[]}]},harnesses:[{id:'codex',name:'Codex',state:'connected',read:'hook',hook_registered:true,detected:true,last_status:'FAILED collection test',job:{last_exit:0}}],backups:{lanes:[{lane:'waiting-producer',delivery:'waiting'},{lane:'unknown-producer'},{lane:'accepted-producer',delivery:'accepted'}]}});
   const html=$('system-home').innerHTML,text=$('system-home').textContent;
   assert('source labels cannot inject HTML',!$('system-home').querySelector('img'));
   assert('overview keeps review in navigation',!text.includes('Needs your attention')&&$('review-count').textContent==='3');
   $('review-tab').click();const reviewText=$('system-home').textContent;
   assert('gate uses user-facing language',reviewText.includes('2 proposals ready for your review')&&!reviewText.includes('internal command text'));
   assert('waiting is not accepted',reviewText.includes('Published · waiting for hub acceptance'));
   assert('missing delivery stays unknown',reviewText.includes('Acceptance unverified'));
   $('home-tab').click();
   assert('collection failure overrides runner success',text.includes('Last collection failed'));
   assert('loaded remains unverified',text.includes('loading into a model are unverified'));
   assert('nodes come first',$('system-home').querySelector('.home-grid').firstElementChild.textContent.startsWith('Nodes'));
   Home.context({receipts:[{topic:'Unrelated context',producer:'raw/other-lane',cards:2,prepared_at:new Date().toISOString(),path:'raw/other-lane/brain-load-usage.md'}],total:1});
   $('system-home').querySelector('.home-tools button').click();
   assert('tool selection never borrows unrelated context',!$('system-home').querySelector('.home-packs').textContent.includes('Unrelated context'));
   assert('tool selection leaves acknowledgement unknown',$('system-home').querySelector('.home-packs').textContent.includes('Loading unconfirmed'));
   const allContext=[...$('system-home').querySelectorAll('button')].find(b=>b.textContent==='All context');allContext.click();
   assert('all context restores archive receipts',$('system-home').querySelector('.home-packs').textContent.includes('Unrelated context'));
   Home.status({request:999,error:'LATE_RESPONSE_SENTINEL'});
   assert('late responses ignored',!$('system-home').textContent.includes('LATE_RESPONSE_SENTINEL'));
   window.sovNewCapture();$('title').value='Unsaved QA draft';$('body').value='Preserve this draft.';
   window.confirm=()=>false;$('home-tab').click();
   assert('cancelled navigation preserves draft',!$('editor').hidden&&$('body').value==='Preserve this draft.');
   window.sovDeliver('local',{action:'read',request:-1,title:'old result',text:'OLD_READ'});
   assert('stale read cannot replace editor',!$('editor').hidden);
   window.confirm=()=>true;$('cancel').click();$('home-tab').click();
   assert('discard permits home navigation',!$('system-home').hidden&&$('editor').hidden);
   Home.archive('/some/other/archive');
   assert('archive mismatch is visible',$('system-home').textContent.includes('Connections below belong to'));
   Home.archive(root);
   window.sovNewCapture();$('title').value='Native capture QA';$('body').value='A capture roundtrip in the isolated test archive.';
   $('editor').requestSubmit();
   const started=Date.now(),poll=setInterval(()=>{
     if(!$('detail').hidden&&$('reader').textContent.includes('capture roundtrip')){
       clearInterval(poll);assert('native capture and read roundtrip',true);$('home-tab').click();finish();
     }else if(Date.now()-started>10000){clearInterval(poll);assert('native capture and read roundtrip',false);finish()}
   },100);
 } catch(e){failures.push(String(e.stack||e));finish()}
 function finish(){window.confirm=originalConfirm;window.webkit.messageHandlers.sov.postMessage({cmd:'clientError',where:'native-qa',msg:JSON.stringify({checks,failures})})}
})();
