const assert = require('node:assert/strict');
let checks = 0; const test = (name, fn) => { fn(); checks++; console.log('PASS ' + name) };

// The pane renders into a host element and posts through the bridge. Stub both so the
// real module runs unchanged: what is asserted below is the markup the owner sees.
const sent = [];
const host = { isConnected: true, className: '', innerHTML: '', querySelector(sel) { return this.innerHTML.includes('id="' + sel.slice(1) + '"') ? { textContent: '' } : null } };
global.window = { webkit: { messageHandlers: { sov: { postMessage: o => sent.push(o) } } } };
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

test('mounting twice does not duplicate the pane', () => {
  view.mount(host, { root: '/a' }); view.mount(host, { root: '/a' });
  assert.equal(host.innerHTML.split('class="set-pane"').length - 1, 1);
});

test('the pane never posts on its own', () => {
  assert.equal(sent.length, 0);
});

test('the scheduled work has a door here and a count', () => {
  const html = paint({ D: { hub: { jobs: { nightly: {}, curate: {} } }, jobs: [{ label: 'a' }, { label: 'b', kick: 'a' }] } });
  assert(html.includes('3 scheduled'));
  assert(html.includes('data-goto-view="jobs"') && html.includes('data-goto-view="setup"'));
});

test('permissions stay closed until one has an open question', () => {
  const settled = paint({ D: { lanes: [{ lane: 'a', read: 'none' }] } });
  assert(settled.includes('<details class="set-more"><summary>1 source</summary>'));
  const drift = paint({ D: { lanes: [{ lane: 'a', read: 'none', findings: [{ level: 'warn', text: 'unsettled' }] }] } });
  assert(drift.includes('<details class="set-more" open><summary>1 source · 1 to settle</summary>'));
});

console.log(checks + ' settings view checks passed.');
