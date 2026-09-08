'use strict';
window.GateModel = (() => {
  const messages = {
    checking:['Checking this proposal','Checking the current card and any existing copies on the approval machine.'],
    ready:['Ready for your decision','The current proposal has been checked. Approval will check it again before making a change.'],
    type_conflict:['Two card types need reconciling','This name already exists under a different card type. Compare the cards below and keep one canonical card before approving this update.'],
    update_conflict:['An existing card needs a merge','This proposal would replace an existing card, but it has not been marked as a merged update. Compare both versions before proceeding.'],
    changed:['The proposal changed','Nothing was approved by this request. Check the latest version and review it before deciding again.'],
    missing:['This proposal is no longer waiting','It may have been handled elsewhere. Refresh the queue to see its current state.'],
    invalid:['This proposal needs correction','Its labels are incomplete or unsupported. Correct the proposal before approving it.'],
    unavailable:['Could not check the approval machine','Check your connection and try Check again. Approval stays unavailable until the current proposal can be checked.'],
    running:['Saving your decision','Keep this window open while the approval machine finishes. Do not submit the same decision again.'],
    approved:['Approved','The card is now in your trusted archive.'],
    rejected:['Rejected','The proposal was moved to the rejected archive.'],
    sync_pending:['Decision saved; sync needs attention','The change is present on the approval machine, but its commit or sync could not be confirmed. Do not approve again. Check the connection and archive sync.'],
    failed:['Your decision did not complete','The proposal is still waiting. Check it again before retrying. Your click has not been reported as a success.'],
    uncertain:['The result could not be confirmed','The connection ended before the result was confirmed. The decision may have completed. Refresh the queue before trying again.'],
    busy:['A decision is already running','Wait for its result before making another decision.']
  };
  function describe(state){return messages[state]||messages.uncertain}
  function canApprove(check,pending){return !pending&&check?.state==='ready'&&/^[a-f0-9]{64}$/.test(check.fingerprint||'')}
  function canReject(check,pending){return !pending&&['ready','type_conflict','update_conflict'].includes(check?.state)&&/^[a-f0-9]{64}$/.test(check.fingerprint||'')}
  return {describe,canApprove,canReject};
})();
