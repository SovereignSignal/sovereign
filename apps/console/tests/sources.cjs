const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const box = {window:{},URL}; vm.createContext(box);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ui/status-model.js'),'utf8'),box);
const S = box.window.SovStatus;

// A lane whose own contract says retired is provenance, not a live source, with or
// without a removed harness elsewhere and whatever comment follows the word.
const lanes = [{lane:'old',status:'retired',vault_age_h:50},{lane:'noted',status:'retired   # 2026-10-03: moved',vault_age_h:30},
  {lane:'live',status:'onboarded',vault_age_h:1},{lane:'manifest',status:'onboarded',retired:true,vault_age_h:1}];
for (const harnesses of [[], [{id:'gone',state:'removed',lane:'gone-lane'}]]) {
  const D = S.associations({lanes:lanes.map(l=>({...l})),harnesses});
  const retired = Object.fromEntries(D.lanes.map(l=>[l.lane,!!l.retired]));
  assert.deepEqual(retired,{old:true,noted:true,live:false,manifest:true},JSON.stringify(harnesses));
  assert.deepEqual({...S.assess(D).completeness.producers},{delivering:1,total:1});
}

// A lane written by a mirror on another device reads the same in Sources as on Today:
// the fresher of the mirror's last run and the hub's newest file, at the remote cadence.
const remote = (age, status) => ({machine:{host:'here'},hub:{lanes:{'tool-there':{age_h:age}}},
  lanes:[{lane:'tool-there',status,vault_age_h:age}],
  fleet:{hosts:[{host:'here',harnesses:[{harness:'tool',lane:'tool-here',run_age_h:50}]},{host:'there',harnesses:[{harness:'tool',lane:'tool-there',run_age_h:age+5}]}]}});
const where = A => { const all = k => A[k].flatMap(x => x.members || [x]).some(x => x.name === 'tool on there'); return all('need') ? 'down' : all('stale') ? 'late' : all('fresh') ? 'live' : 'none'; };
for (const [age, verdict] of [[0.5,'live'],[1.5,'late'],[32,'down']]) {
  const D = S.associations(remote(age)), m = S.remoteMirror(D, 'tool-there');
  assert.equal(m.age_h, age);
  assert.equal(where(S.assess(D)), verdict, 'Today at ' + age + 'h');
  assert.equal(m.age_h > 2 * m.cadence_h ? 'down' : m.age_h > m.cadence_h ? 'late' : 'live', verdict, 'Sources at ' + age + 'h');
}
assert.equal(S.remoteMirror(remote(1), 'tool-here'), null, 'this machine\'s own mirror is not remote');
assert.equal(where(S.assess(S.associations(remote(32, 'retired')))), 'none', 'a mirror into a retired lane is not late');
console.log('Sources: retired contracts survive the projection; remote mirrors read the same as on Today.');

// The Claude Code lane's week of session capture, read from sessions/MANIFEST.md. Parts after
// the first are left out at zero; a lane waiting on its model says only that, in amber.
process.env.TZ = 'UTC';
const week = (o) => ({distilled:0,captures:0,skipped:0,waiting:0,failed:0,refused:0,waiting_reason:null,...o});
assert.deepEqual({...S.sessionLine(week({distilled:3,captures:2,skipped:41,waiting:1}))},
  {text:'3 sessions distilled this week, 2 captures · 41 skipped · 1 waiting',warn:false});
assert.equal(S.sessionLine(week({})).text,'0 sessions distilled this week');
assert.equal(S.sessionLine(week({distilled:1,captures:1})).text,'1 session distilled this week, 1 capture');
assert.equal(S.sessionLine(week({skipped:5,failed:2,refused:1})).text,'0 sessions distilled this week · 5 skipped · 2 failed · 1 refused');
const now = Date.parse('2026-10-21T15:00:00Z');
assert.deepEqual({...S.sessionLine(week({distilled:3,waiting:2,waiting_reason:'model unreachable since 2026-10-21T14:05Z'}),now)},
  {text:'waiting: model unreachable since 14:05',warn:true});
assert.equal(S.sessionLine(week({waiting_reason:'model unreachable since 2026-10-19T08:30Z'}),now).text,'waiting: model unreachable since 2026-10-19 08:30');
assert.equal(S.sessionLine(week({waiting_reason:'capture is not ready'}),now).text,'waiting: capture is not ready');
assert.equal(S.sessionLine(null),null);
assert.equal(S.sessionLine(undefined),null);
for (const t of [S.sessionLine(week({distilled:3,captures:2,skipped:41,waiting:1})).text]) assert.doesNotMatch(t,/[–—]/);
console.log('Sources: the session capture line counts the week and names a wait.');
