const fs = require('fs'), assert = require('assert');
const html=fs.readFileSync('apps/console/ui/index.html','utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
new Function(script);
const local=fs.readFileSync('apps/console/ui/local.html','utf8').match(/<script>([\s\S]*)<\/script>/)[1];new Function(local);
const start=script.indexOf('  function backupItems()'),end=script.indexOf('  const selectable',start);
const items=new Function('D','age',script.slice(start,end)+';return backupItems();');
for(const delivery of ['waiting','unknown',undefined]){
 const row=items({backups:{lanes:[{lane:'fixture',delivery,pushed:new Date().toISOString()}]}},String)[0];assert.equal(row.o.state,'warn');
}
const accepted=items({backups:{lanes:[{lane:'fixture',delivery:'accepted',pushed:new Date().toISOString()}]}},String)[0];assert.equal(accepted.o.state,'live');
console.log('Both UI scripts parse; delivery rows cannot show a fresh unaccepted source as healthy.');
