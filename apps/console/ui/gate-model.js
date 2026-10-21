'use strict';
window.GateModel = (() => {
  const messages = {
    checking:['Checking this proposal','Checking the current card and any existing copies on the approval machine.'],
    ready:['Ready for your decision','The current proposal has been checked. Approval will check it again before making a change.'],
    type_conflict:['Two card types need reconciling','This name already exists under a different card type. Compare the cards below and keep one canonical card before approving this update.'],
    update_conflict:['An existing card needs a merge','This proposal would replace an existing card, but it has not been marked as a merged update. Compare both versions before proceeding.'],
    target_conflict:['This update needs consolidation','It names an existing card but uses a different proposal name. Consolidate the evidence under the target card before approving, or reject this draft.'],
    changed:['The proposal changed','Nothing was approved by this request. Check the latest version and review it before deciding again.'],
    missing:['This proposal is no longer waiting','It may have been handled elsewhere. Refresh the queue to see its current state.'],
    invalid:['This proposal needs correction','Its labels are incomplete or unsupported. Correct the proposal before approving it.'],
    unavailable:['Could not check the approval machine','Check your connection and try Check again. Approval stays unavailable until the current proposal can be checked.'],
    resolution_pending:['Resolution needs recovery','The interrupted decision must be checked before another approval. Your original proposal and trusted card were saved on the approval machine. Do not submit again; use Copy recovery request.'],
    running:['Saving your decision','Keep this window open while the approval machine finishes. Do not submit the same decision again.'],
    approved:['Approved','The card is now in your trusted archive.'],
    rejected:['Rejected','The proposal was moved to the rejected archive.'],
    sync_pending:['Decision saved; sync needs attention','The change is present on the approval machine, but its commit or sync could not be confirmed. Do not approve again. Check the connection and archive sync.'],
    failed:['Your decision did not complete','The proposal is still waiting. Check it again before retrying. Your click has not been reported as a success.'],
    uncertain:['The result could not be confirmed','The approval machine did not return a confirmed result. The decision may have completed. Refresh the queue before trying again.'],
    busy:['A decision is already running','Wait for its result before making another decision.']
  };
  function describe(state){return messages[state]||messages.uncertain}
  function canApprove(check,pending){return !pending&&check?.state==='ready'&&/^[a-f0-9]{64}$/.test(check.fingerprint||'')}
  function canResolve(check,pending){const c=check?.existing?.[0],folders={entity:'entities',concept:'concepts',synthesis:'syntheses',plan:'syntheses',review:'syntheses'};return !pending&&check?.state==='type_conflict'&&check.update===true&&check.existing.length===1&&!!folders[c?.type]&&typeof c.path==='string'&&c.path.split('/').at(-2)===folders[c.type]&&c.type!==check.proposal?.type&&/^[a-f0-9]{64}$/.test(check.fingerprint||'')}
  function canReject(check,pending){return !pending&&['ready','type_conflict','update_conflict','target_conflict'].includes(check?.state)&&/^[a-f0-9]{64}$/.test(check.fingerprint||'')}
  // Age changes every status tick; content, routing and review metadata do not.
  function reviewKey(status,slug){
    const hub=status.hub||{},proposal=(hub.proposals||[]).find(p=>p.slug===slug);
    if(!proposal)return null;
    const stable=Object.keys(proposal).filter(k=>k!=='age_h').sort().map(k=>[k,proposal[k]]);
    return JSON.stringify([status.machine?.vault,hub.via||'local',hub.reachable,stable]);
  }
  // Bind the connected queue to the archive selected in the native app. Missing
  // observations must never read as an empty queue. Status currently caps rows at 60.
  function queue(status,root,known=true){
    const blocked=(state,title,message)=>({state,title,message,available:false,proposals:[],count:null});
    if(!known)return blocked('loading','Opening Review','Reading the selected archive.');
    if(!root)return blocked('no_archive','Open an archive to review','Choose the archive whose knowledge you want to review.');
    if(!status)return blocked('loading','Checking your review queue','Waiting for the connected system to report its proposals.');
    if(status._status?.pending&&!status._status?.error)return blocked('loading','Checking your review queue','Earlier observations cannot authorize a decision.');
    if(status._status?.pending||status._status?.stale)return blocked('unavailable','Review status unavailable',status._status.error||'Refresh to read the current queue. Earlier observations cannot authorize a decision.');
    if(status.error)return blocked('unavailable','Review status unavailable','Refresh to reconnect. Your last observation cannot confirm which proposals are still waiting.');
    if(status.machine?.connected!==true)return blocked('not_connected','Review is not connected','This archive can hold local notes. Connect its review service in Settings to receive proposals.');
    if(status.machine?.vault!==root)return blocked('different_archive','This archive has a different connection','The connected system belongs to another archive. Open that archive to review its proposals.');
    const h=status.hub||{};
    if(h.reachable!==true)return blocked('offline','Review service unavailable','Reconnect to the approval machine, then refresh. Its current queue is unverified.');
    const proposals=h.proposals;
    if(!Number.isSafeInteger(h.pending)||h.pending<0||!Array.isArray(proposals)||h.pending<proposals.length||
       proposals.some(p=>!p||typeof p.slug!=='string'||!/^[a-z0-9][a-z0-9_-]*$/.test(p.slug))||new Set(proposals.map(p=>p.slug)).size!==proposals.length)
      return blocked('incomplete','The review queue was not fully reported','Refresh to retrieve a valid proposal list. An incomplete report does not mean your queue is clear.');
    if(h.pending&&!proposals.length)return blocked('incomplete','Proposals are waiting to load',h.pending+' reported by the review service. Refresh to load their details.');
    return {state:h.pending?'ready':'empty',available:true,proposals,count:h.pending,
      title:h.pending?'Awaiting your decision':'You’re caught up',
      message:h.pending?(proposals.length<h.pending?'Showing '+proposals.length+' of '+h.pending+' proposals. Refresh after decisions to load more.':'Compare each proposal with existing knowledge, then decide what to keep.'):'The review service reported no waiting proposals in its latest observation.'};
  }
  // A proposal drawn from a session capture (sov-status `session`): which session, and the
  // turns its evidence rests on. The span is UTC, as the capture wrote it.
  function spanText(span){
    const m=/^(\d{4}-\d\d-\d\d)T(\d\d:\d\d)Z\.\.(\d{4}-\d\d-\d\d)T(\d\d:\d\d)Z$/.exec(span||'');
    if(!m)return span||'';
    return m[1]+' '+m[2]+' to '+(m[3]===m[1]?'':m[3]+' ')+m[4]+' UTC';
  }
  function sessionLine(p){
    const s=p?.session;
    if(!s||typeof s!=='object')return null;
    const turns=(Array.isArray(s.evidence)?s.evidence:[]).filter(t=>/^T\d+$/.test(t));
    const parts=[s.title,s.project,spanText(s.span)].filter(x=>typeof x==='string'&&x.trim()).map(x=>x.trim());
    if(turns.length)parts.push('turns '+turns.join(', '));
    return 'From a Claude Code session'+(parts.length?': '+parts.join(', '):'');
  }
  // Open session runs claude --resume in Terminal, so only on the machine that holds the
  // transcript, and only for a session id the bridge will accept (a UUID).
  const SESSION_UUID=/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
  function canOpenSession(p){const s=p?.session;return !!s&&s.local===true&&typeof s.id==='string'&&s.id.length===36&&SESSION_UUID.test(s.id)}
  return {describe,canApprove,canReject,canResolve,reviewKey,queue,sessionLine,canOpenSession,decisionTimeoutMS:120000};
})();
