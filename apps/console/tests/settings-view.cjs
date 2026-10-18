const assert = require('node:assert/strict');
let checks = 0; const test = (name, fn) => { fn(); checks++; console.log('PASS ' + name) };

// The pane renders into a host element and posts through the bridge. Stub both so the
// real module runs unchanged: what is asserted below is the markup the owner sees.
const sent = [];
const host = { isConnected: true, className: '', innerHTML: '', querySelector(sel) { return this.innerHTML.includes('id="' + sel.slice(1) + '"') ? { textContent: '' } : null } };
global.window = { webkit: { messageHandlers: { sov: { postMessage: o => sent.push(o) } } } };
const listeners = {}, controls = {};
global.document = { addEventListener(k, f) { listeners[k] = f; }, getElementById: id => controls[id] || null };
require(process.argv[2] || '../ui/settings-view.js');
const view = global.window.SovSettings;
const paint = ctx => { host.innerHTML = ''; view.mount(host, Object.assign({ S: {}, D: null, root: null, pinned: false }, ctx)); return host.innerHTML };

const app = extra => ({ machine: Object.assign({ app: { installed: true, version: '0.5.6', build: '28', source_commit: 'abc1234' }, template_rev: 'abc1234 subject' }, extra) });

test('an archive that is open is named, and one that is not says so', () => {
  assert(paint({ root: '/Owner/Research' }).includes('/Owner/Research'));
  const none = paint({ root: null });
  assert(none.includes('No archive is open'));
  // Nothing to reveal when nothing is open, so the button is not offered.
  assert(!none.includes('set-reveal'));
});

test('a current build offers no update action', () => {
  const html = paint({ D: app() });
  assert(html.includes('is the newest build'));
  assert(html.includes('Check again'));
  assert(!html.includes('id="set-update">Update now'));
});

test('a behind build offers the action and shows both revisions', () => {
  const html = paint({ D: app({ template_rev: 'def5678 newer' }) });
  assert(html.includes('A newer version is ready'));
  assert(html.includes('class="brass" id="set-update"'));
  assert(html.includes('abc1234') && html.includes('def5678'));
});

test('a build newer than this source is not called a newer version', () => {
  const html = paint({ D: app({ app: { installed: true, version: '0.6.0', build: '39', source_commit: 'abc1234', behind: false }, template_rev: 'def5678 older' }) });
  assert(!html.includes('A newer version'));
  assert(html.includes('nothing newer to install'));
  assert(!html.includes('id="set-update">Update now'));
});

test('an unstamped build claims no agreement it cannot check', () => {
  const html = paint({ D: app({ app: { installed: true, version: '0.1', build: '1' } }) });
  assert(html.includes('predates update checking'));
  assert(!html.includes('newest build'));
  assert(!html.includes('is ready to install'));
});

test('a source revision that cannot be read offers no build', () => {
  const html = paint({ D: app({ template_rev: '' }) });
  assert(html.includes('cannot be checked right now'));
  assert(!html.includes('class="brass" id="set-update"'));
});

test('contribute-only and read-and-contribute are told apart', () => {
  const html = paint({ D: { lanes: [
    { lane: 'alpha', read: 'none', write: 'git-branch', gear: 'ask-first' },
    { lane: 'beta', read: 'hook', read_scope: 'knowledge + own lane', write: 'connector', gear: 'routine' }] } });
  assert(html.includes('Contribute only') && html.includes('reads nothing from this archive'));
  assert(html.includes('Read and contribute') && html.includes('knowledge + own lane'));
  assert(html.includes('ask-first') && html.includes('routine'));
});

test('a lane with no declared read is contribute-only, not unknown', () => {
  assert(paint({ D: { lanes: [{ lane: 'x' }] } }).includes('Contribute only'));
});

test('read_scope true is a flag, never a scope to print', () => {
  // A producer that declares `read_scope: true` - a flag, not a scope - rendered
  // as "reads true" until 2026-09-21.
  const html = paint({ D: { lanes: [{ lane: 'gamma', host: 'Worker-Z', read: 'git', read_scope: true }] } });
  assert(!/reads\s+true/.test(html), 'a boolean read_scope must not be printed as a scope');
  assert(html.includes('reads via git'));
});

test('the read mechanism keeps the parenthetical that says when it reads', () => {
  const html = paint({ D: { lanes: [{ lane: 'a', host: 'Laptop-A', read: 'brain-load (session-start hook)' }] } });
  assert(html.includes('reads via brain-load (session-start hook)'));
});

test('a declared string scope is named alongside the mechanism', () => {
  const html = paint({ D: { lanes: [{ lane: 'a', host: 'Laptop-A', read: 'hook', read_scope: 'knowledge + own lane' }] } });
  assert(html.includes('scoped to knowledge + own lane'));
});

test('lanes are grouped by the machine they run on, busiest first', () => {
  const html = paint({ D: { lanes: [
    { lane: 'a', host: 'Laptop-A' }, { lane: 'b', host: 'Worker-Z' }, { lane: 'c', host: 'Laptop-A' }, { lane: 'd', host: 'Laptop-A' }] } });
  const hosts = [...html.matchAll(/class="set-host"><th colspan="6">([^<]*)<small>([^<]*)</g)].map(m => [m[1], m[2]]);
  assert.deepEqual(hosts, [['Laptop-A', '3 lanes'], ['Worker-Z', '1 lane']]);
});

test('a lane with no host is placed, not dropped', () => {
  const html = paint({ D: { lanes: [{ lane: 'orphan' }] } });
  assert(html.includes('orphan'));
  assert(html.includes('unplaced'));
});

test('the producer says what the tool is, beside the lane name', () => {
  assert(paint({ D: { lanes: [{ lane: 'some-tool', host: 'Laptop-A', producer: 'Cursor (GUI composer + CLI agent)' }] } })
    .includes('Cursor (GUI composer + CLI agent)'));
});

test('declared drift is shown in line and marks its row', () => {
  const html = paint({ D: { lanes: [{ lane: 'delta', read: 'none', findings: [{ level: 'warn', text: 'declares a read_scope while reading nothing' }] }] } });
  assert(html.includes('declares a read_scope while reading nothing'));
  assert(html.includes('<tr class="warn">'));
});

test('a lane the owner retired does not keep asking an answered question', () => {
  assert(!paint({ D: { lanes: [{ lane: 'gone', associated: false }] } }).includes('gone'));
});

test('an info note is an answer already given, so it never marks the row', () => {
  const html = paint({ D: { lanes: [{ lane: 'epsilon', read: 'none', retired: true,
    findings: [{ level: 'info', text: 'retired; kept as provenance, not a live wire' }] }] } });
  assert(html.includes('retired; kept as provenance'));
  assert(!html.includes('class="warn"'), 'an info-only lane must not read as drift');
  assert(html.includes('class="retired"'));
});

test('a retired lane with a real question still raises it, once', () => {
  const html = paint({ D: { lanes: [{ lane: 'x', read: 'none', retired: true,
    findings: [{ level: 'info', text: 'kept as provenance' }, { level: 'warn', text: 'the law never names this lane' }] }] } });
  assert(html.includes('class="warn retired"'));
  // One body row, plus the column header and the one host band above it.
  assert.equal(html.split('<tr').length - 1, 3);
});

test('lane names are escaped, never injected', () => {
  const html = paint({ D: { lanes: [{ lane: '<img src=x onerror=1>', read: 'none' }] } });
  assert(!html.includes('<img'));
  assert(html.includes('&lt;img'));
});

test('preferences reflect what is saved, not defaults', () => {
  const html = paint({ S: { appearance: 'dark', where: 'menubar', closeQuits: true, loginItem: true, refresh: 300, loginState: 'on' }, pinned: true });
  assert(html.includes('value="dark" selected'));
  assert(html.includes('value="menubar" checked'));
  assert(html.includes('id="s-closequits" checked') && html.includes('id="s-login" checked'));
  assert(html.includes('value="300" selected'));
  assert(html.includes('id="s-pin" checked'));
  assert(html.includes('Registered with macOS'));
});

test('quit on close is offered only where it applies: the Dock', () => {
  assert(paint({ S: { where: 'dock' } }).match(/id="s-closequits" (?!disabled)[^>]*>/));
  for (const where of ['menubar', 'both']) {
    const html = paint({ S: { where, closeQuits: true } });
    assert(/id="s-closequits" checked disabled/.test(html), where + ' keeps running in the menu bar');
    assert(/id="s-closequits-note">Dock only</.test(html));
  }
  // Choosing Dock before saving enables it at once, and choosing away disables it again.
  controls['s-closequits'] = { disabled: true }; controls['s-closequits-note'] = { hidden: false };
  listeners.change({ target: { name: 'set-where', value: 'dock' } });
  assert.deepEqual([controls['s-closequits'].disabled, controls['s-closequits-note'].hidden], [false, true]);
  listeners.change({ target: { name: 'set-where', value: 'menubar' } });
  assert.deepEqual([controls['s-closequits'].disabled, controls['s-closequits-note'].hidden], [true, false]);
});

test('a status not yet read, or not readable, claims nothing about the build, jobs or lanes', () => {
  const falsehoods = /cannot identify|Install once|None reported|No producer lanes/;
  for (const [D, said] of [[null, 'Checking'], [{ _status: { pending: true } }, 'Checking'],
                           [{ error: 'System status could not be read (exit 1).', _status: { pending: false, stale: true } }, 'Status unavailable']]) {
    const html = paint({ D });
    assert(!falsehoods.test(html), JSON.stringify(D));
    assert.equal(html.split(said).length - 1, 3, 'Version, Jobs and Permissions each say so: ' + JSON.stringify(D));
    assert(html.includes('data-goto-view="jobs"'), 'the door to Jobs stays open');
  }
});

test('mounting twice does not duplicate the pane', () => {
  view.mount(host, { root: '/a' }); view.mount(host, { root: '/a' });
  assert.equal(host.innerHTML.split('class="set-pane"').length - 1, 1);
});

test('the pane never posts on its own', () => {
  assert.equal(sent.length, 0);
});

test('trust calibration shows progress before background landing is offered', () => {
  const html = paint({ root: '/Owner/Research', curator: { hub: false, key_saved: true, installed: true, loaded: true, pending: 2,
    trust: 'ask-first', trust_record: { state: 'ask-first', clean_streak: 4, threshold: 10, eligible: false } } });
  assert(html.includes('Background landing is off'));
  assert(html.includes('4 of 10 clean routine decisions'));
  assert(!html.includes('id="set-cur-trust"'));
});

test('an earned trust grant is one explicit action', () => {
  const html = paint({ root: '/Owner/Research', curator: { hub: false, key_saved: true, installed: true, loaded: true, pending: 0,
    trust: 'ask-first', trust_record: { state: 'ask-first', clean_streak: 10, threshold: 10, eligible: true } } });
  assert(html.includes('The curator has earned more room'));
  assert(html.includes('id="set-cur-trust">Let routine cards land'));
});

test('background landing names its landed cards and can be revoked', () => {
  const html = paint({ root: '/Owner/Research', curator: { hub: false, key_saved: true, installed: true, loaded: true, pending: 1,
    trust: 'act-and-report', trust_record: { state: 'act-and-report', auto_landed_30d: 3, auto_reverted_30d: 1,
      recent_auto_landed: [{ slug: 'garden-plan', type: 'concept', confidence: 'high', ts: '2026-10-18T12:00:00+00:00', reverted: false }] } } });
  assert(html.includes('Background landing is on'));
  assert(html.includes('3 landed on their own in the last 30 days'));
  assert(html.includes('garden-plan'));
  assert(html.includes('data-cur-retire="garden-plan">Retire…'));
  assert(html.includes('id="set-cur-untrust">Ask first again'));
});

test('a disagreeing trust switch offers repair and reads as ask-first', () => {
  const html = paint({ root: '/Owner/Research', curator: { hub: false, key_saved: true, installed: true, loaded: true, pending: 0,
    trust: 'incomplete', trust_record: { state: 'incomplete', repair_needed: true } } });
  assert(html.includes('Trust needs repair'));
  assert(html.includes('id="set-cur-trust">Repair trust'));
});

test('the scheduled work has a door here and a count', () => {
  const html = paint({ D: { hub: { jobs: { nightly: {}, curate: {} } }, jobs: [{ label: 'a' }, { label: 'b', kick: 'a' }] } });
  assert(html.includes('3 scheduled'));
  // The Jobs header reads the same count, with the lanes inside the runner apart.
  assert.deepEqual({ ...view.jobCount({ hub: { jobs: { nightly: {}, curate: {} } }, jobs: [{ label: 'a' }, { label: 'b', kick: 'a' }] }) }, { jobs: 3, lanes: 1 });
  assert(html.includes('data-goto-view="jobs"') && html.includes('data-goto-view="setup"'));
});

test('permissions stay closed until one has an open question', () => {
  const settled = paint({ D: { lanes: [{ lane: 'a', read: 'none' }] } });
  assert(settled.includes('<details class="set-more"><summary>1 source</summary>'));
  const drift = paint({ D: { lanes: [{ lane: 'a', read: 'none', findings: [{ level: 'warn', text: 'unsettled' }] }] } });
  assert(drift.includes('<details class="set-more" open><summary>1 source · 1 to settle</summary>'));
});

console.log(checks + ' settings view checks passed.');
