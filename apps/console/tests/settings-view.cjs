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

const app = extra => ({ machine: Object.assign({ app: { installed: true, version: '0.5.6', build: '28', source_commit: 'abc1234' }, template: '/Owner/src', template_rev: 'abc1234 subject' }, extra) });
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const RELEASE = '<button class="brass" id="set-update">Check for updates</button>';
const SOURCE = 'id="set-update-source">Update from source';

test('an archive that is open is named, and one that is not says so', () => {
  assert(paint({ root: '/Owner/Research' }).includes('/Owner/Research'));
  const none = paint({ root: null });
  assert(none.includes('No archive is open'));
  // Nothing to reveal when nothing is open, so the button is not offered.
  assert(!none.includes('set-reveal'));
});

test('a build current with this source offers only the release check', () => {
  const html = paint({ D: app() });
  assert(html.includes('You are running Sovereign 0.5.6 build 28.'));
  assert(html.includes('is the newest build'), 'the source comparison is kept behind Details');
  assert(html.includes(RELEASE));
  assert(!html.includes(SOURCE));
});

test('a behind build also offers the source update and shows both revisions', () => {
  const html = paint({ D: app({ template_rev: 'def5678 newer' }) });
  assert(html.includes('A newer version is ready'));
  assert(html.includes(RELEASE) && html.includes(SOURCE));
  assert(html.includes('abc1234') && html.includes('def5678'));
});

test('a behind build with no known source location offers no source update', () => {
  const html = paint({ D: app({ template: '', template_rev: 'def5678 newer' }) });
  assert(html.includes(RELEASE));
  assert(!html.includes(SOURCE));
});

test('a build newer than this source is not called a newer version', () => {
  const html = paint({ D: app({ app: { installed: true, version: '0.6.0', build: '39', source_commit: 'abc1234', behind: false }, template_rev: 'def5678 older' }) });
  assert(!html.includes('A newer version'));
  assert(html.includes('nothing newer to install'));
  assert(html.includes(RELEASE) && !html.includes(SOURCE));
});

test('an app found in neither Applications folder says where it can check itself from', () => {
  const html = paint({ D: app({ app: { installed: false } }) });
  assert(html.includes('cannot identify'));
  // Either folder works; a newcomer is not sent to build from source to get updates.
  assert(html.includes('~/Applications') && html.includes('/Applications or'), html);
  assert(!html.includes('Install once'));
});

test('an unstamped build claims no agreement it cannot check', () => {
  const html = paint({ D: app({ app: { installed: true, version: '0.1', build: '1' } }) });
  assert(html.includes('predates update checking'));
  assert(!html.includes('newest build'));
  assert(!html.includes('is ready to install'));
  // Building from source stamps it, so that stays on offer beside the release check.
  assert(html.includes(RELEASE) && html.includes(SOURCE));
});

test('a source revision that cannot be read offers no build', () => {
  const html = paint({ D: app({ template_rev: '' }) });
  assert(html.includes('cannot be checked right now'));
  assert(html.includes(RELEASE) && !html.includes(SOURCE));
});

test('the release check is offered for every identified build', () => {
  for (const extra of [{}, { template_rev: 'def5678 newer' }, { template_rev: '' }, { template: '' },
                       { app: { installed: true, version: '0.6.0', build: '39', source_commit: 'abc1234', behind: false }, template_rev: 'def5678 older' }])
    assert(paint({ D: app(extra) }).includes(RELEASE), JSON.stringify(extra));
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

test('the curator provider can be chosen and names itself in the copy', () => {
  const providers = [
    { id: 'anthropic', name: 'Anthropic', hint: 'sk-ant-…', key_saved: true },
    { id: 'openai', name: 'OpenAI', hint: 'sk-…', key_saved: false },
    { id: 'gemini', name: 'Google Gemini', hint: 'API key…', key_saved: false },
    { id: 'grok', name: 'xAI Grok', hint: 'xai-…', key_saved: false },
    { id: 'muse', name: 'Muse', hint: 'API key…', key_saved: false }];
  const html = paint({ root: '/Owner/Research', curator: { hub: false, key_saved: false, installed: false, loaded: false, pending: 0,
    provider: 'grok', providers, trust: 'ask-first', trust_record: { state: 'ask-first' } } });
  assert(html.includes('data-cur-provider="muse"'));
  assert(html.includes('data-cur-provider="grok" class="brass"'));
  assert(html.includes('Add your xAI Grok API key'));
  assert(html.includes('placeholder="xai-…"'));
  assert(html.includes('sends new material to xAI Grok'));
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

test('import appears only for an open archive and waits for its prompt', () => {
  assert(!paint({ root: null }).includes('set-imp-text'));
  const loading = paint({ root: '/a', imports: null });
  assert(loading.includes('Loading the prompt') && loading.includes('id="set-imp-preview"'));
  assert(!loading.includes('Copy prompt') && !loading.includes('id="set-imp-apply"'));
});

test('import escapes the prompt, the pasted answer and the plan', () => {
  view.importText('## </textarea><script>x()</script>');
  const html = paint({ root: '/a', imports: { prompt: 'Say "hi" & <b>list</b>', plan: '<img src=x onerror=y>' } });
  assert(!html.includes('<script>x()') && html.includes('&lt;/textarea&gt;'));
  assert(html.includes('data-text="Say &quot;hi&quot; &amp; &lt;b&gt;list&lt;/b&gt;"'));
  assert(!html.includes('<img src=x') && html.includes('&lt;img src=x'));
  view.importText('');
});

test('import offers Import only after a preview, and keeps the answer across redraws', () => {
  const before = paint({ root: '/a', imports: { prompt: 'p' } });
  assert(before.includes('Copy prompt') && !before.includes('id="set-imp-apply"'));
  listeners.input({ target: { id: 'set-imp-text', value: '## Garden\nYou plan gardens offline.' } });
  const after = paint({ root: '/a', imports: { prompt: 'p', plan: '2 new', ready: true } });
  assert(after.includes('class="brass" id="set-imp-apply"'));
  assert(after.includes('## Garden\nYou plan gardens offline.</textarea>'));
  assert.equal(view.importText(), '## Garden\nYou plan gardens offline.');
  view.importText('');
});

test('each provider has a key guide that opens until a key is saved and links only over https', () => {
  const providers = [['anthropic', 'Anthropic'], ['openai', 'OpenAI'], ['gemini', 'Google Gemini'], ['grok', 'xAI Grok'], ['muse', 'Muse']]
    .map(([id, name]) => ({ id, name, hint: 'k', key_saved: false }));
  const cur = (provider, key_saved) => ({ hub: false, key_saved, installed: key_saved, loaded: key_saved, pending: 0,
    provider, providers, trust: 'ask-first', trust_record: { state: 'ask-first' } });
  for (const [id, name] of providers.map(p => [p.id, p.name])) {
    const html = paint({ root: '/a', curator: cur(id, false) });
    assert(html.includes(`<details class="set-more" open><summary>Get your ${name} key</summary>`), id);
    assert(html.includes('never your password'), id);
    for (const [, url] of html.matchAll(/data-act="openurl" data-url="([^"]+)"/g)) assert(url.startsWith('https://'), id + ' ' + url);
  }
  assert(!paint({ root: '/a', curator: cur('muse', false) }).includes('data-act="openurl"'));
  assert(paint({ root: '/a', curator: cur('anthropic', false) }).includes('data-url="https://platform.claude.com/settings/keys"'));
  // Once the key is in, the guide steps aside but stays one click away.
  assert(paint({ root: '/a', curator: cur('openai', true) }).includes('<details class="set-more"><summary>Get your OpenAI key</summary>'));
});


// Settings › Session capture: the status `sov ingest sessions status --json` prints.
const SES = extra => Object.assign({ tool: 'claude-code', enabled: false, available: true, mode: 'hubless', reason: '',
  distiller: { provider: 'anthropic', model: 'claude-x', name: 'Anthropic' },
  budget: { calls_per_tick: 3, calls_per_day: 30, chars_per_tick: 60000, used_today: 0 },
  week: { distilled: 0, captures: 0, skipped: 0, waiting: 0, failed: 0, refused: 0 }, waiting: null,
  projects: [
    { path: '/Owner/src/garden', label: 'garden', sessions: 4, on: true, kind: 'normal', denied: false },
    { path: '/private/tmp/scratch', label: 'scratch', sessions: 1, on: false, kind: 'temp', denied: false },
    { path: '/Owner/Research', label: 'Research', sessions: 2, on: false, kind: 'archive', denied: false }],
  next: [{ tool: 'codex', label: 'Codex' }] }, extra);
const CUR = { hub: true };
// The Session capture section alone, so other sections' strings never leak into an assertion.
const sesOf = html => { const i = html.indexOf('<h2>Session capture</h2>'); assert(i >= 0, 'no Session capture section');
  const start = html.lastIndexOf('<div class="set-sect">', i), end = html.indexOf('<div class="set-sect">', i);
  return html.slice(start, end < 0 ? undefined : end); };
// mount merges into the last ctx, so every paint names the preview keys, as index.html does.
const ses = ctx => sesOf(paint(Object.assign({ root: '/Owner/Research', curator: CUR, sessionsPlan: '', sessionsPreviewed: false }, ctx)));

test('session capture says Checking until its status is read, and only for an open archive', () => {
  assert(!paint({ root: null }).includes('Session capture'));
  const html = ses({ sessions: null });
  assert(html.includes('Checking…'));
  assert(!html.includes('id="set-ses-preview"') && !html.includes('id="set-ses-on"'));
});

test('a client Mac says capture is off here and why, with no controls', () => {
  const reason = "This Mac sends its work to a hub archive. Session capture needs the archive's own model, which runs on the hub, so it stays off here.";
  const html = ses({ sessions: SES({ mode: 'client', available: false, reason }), sessionsPreviewed: true, sessionsPlan: 'plan' });
  assert(html.includes('Session capture is off on this Mac.'));
  assert(html.includes(esc(reason)));
  for (const id of ['set-ses-on', 'set-ses-off', 'set-ses-preview']) assert(!html.includes(`id="${id}"`), id);
  assert(!html.includes('data-ses-path'));
});

test('a client Mac with capture carried on from another role still offers Turn off, and only that', () => {
  const html = ses({ sessions: SES({ mode: 'client', available: false, enabled: true, reason: 'r' }), sessionsPreviewed: true, sessionsPlan: 'plan' });
  assert(html.includes('Session capture is off on this Mac.'));
  assert(html.includes('id="set-ses-off"'));
  for (const id of ['set-ses-on', 'set-ses-preview']) assert(!html.includes(`id="${id}"`), id);
  assert(!html.includes('data-ses-path'));
});

test('an archive with no usable model gives the reason and no switch', () => {
  const html = ses({ sessions: SES({ available: false, reason: 'No key is saved for Anthropic. Add one in Settings › Curator.' }), sessionsPreviewed: true });
  assert(html.includes('No key is saved for Anthropic.'));
  assert(!html.includes('id="set-ses-on"'));
  assert(!html.includes('data-ses-path'));
  // A guard fragment still reads as a sentence.
  assert(ses({ sessions: SES({ available: false, reason: 'needs a local model on this archive' }) })
    .includes('Session capture needs a local model on this archive.'));
});

test('off before a preview offers Preview and no Turn on', () => {
  const html = ses({ sessions: SES() });
  assert(html.includes('Claude Code: distill quiet sessions into its lane'));
  assert(html.includes('Codex: next'));
  assert(html.includes('Uses your curator&#39;s provider: Anthropic') || html.includes("Uses your curator's provider: Anthropic"));
  assert(html.includes('Up to 3 sessions a tick and 30 a day, oldest first.'));
  assert(html.includes('id="set-ses-preview"'));
  assert(!html.includes('id="set-ses-on"'));
  assert(!html.includes('id="set-ses-off"'));
});

test('off after a preview shows the plan and offers Turn on', () => {
  const html = ses({ sessions: SES(), sessionsPreviewed: true, sessionsPlan: 'Session capture for Claude Code is off.\n<b>1 would be distilled</b>' });
  assert(html.includes('id="set-ses-on"'));
  assert(html.includes('1 would be distilled') && !html.includes('<b>1 would'), 'the plan is escaped');
  // A preview that has not rendered here does not count.
  assert(!ses({ sessions: SES(), sessionsPlan: 'plan' }).includes('id="set-ses-on"'));
});

test('on shows the week and Turn off, never Turn on', () => {
  const html = ses({ sessions: SES({ enabled: true, week: { distilled: 3, captures: 2, skipped: 41, waiting: 1, failed: 0, refused: 1 },
    waiting: { reason: 'model unreachable', since: '2026-10-21T14:05Z' } }), sessionsPreviewed: true, sessionsPlan: 'plan' });
  assert(html.includes('This week: distilled 3, captures 2, skipped 41, waiting 1, failed 0, refused 1.'));
  assert(html.includes('Waiting: model unreachable since 2026-10-21T14:05Z.'));
  assert(html.includes('id="set-ses-off"'));
  assert(!html.includes('id="set-ses-on"'));
});

test('projects: one checkbox each with its count, temporary folders unchecked, archives a fixed row', () => {
  const html = ses({ sessions: SES() });
  assert(/<input type="checkbox" data-ses-path="\/Owner\/src\/garden" checked>/.test(html));
  assert(/<input type="checkbox" data-ses-path="\/private\/tmp\/scratch">/.test(html), 'a temporary folder starts off');
  assert(html.includes('4 sessions') && html.includes('1 session<'));
  assert(!html.includes('data-ses-path="/Owner/Research"'), 'an archive is never a choice');
  assert(/<input type="checkbox" disabled> Inside an archive: never/.test(html));
  const evil = ses({ sessions: SES({ projects: [{ path: '/a/"><img src=x>', label: '<img src=x>', sessions: 1, on: true, kind: 'normal', denied: false }] }) });
  assert(!evil.includes('<img'));
});

test('sections run Curator, Session capture, Import', () => {
  const html = paint({ root: '/Owner/Research', curator: CUR, sessions: SES() });
  const at = h => html.indexOf(`<h2>${h}</h2>`);
  assert(at('Curator') >= 0 && at('Curator') < at('Session capture') && at('Session capture') < at('Import'));
});

test('no em or en dash in any session capture string', () => {
  const states = [{ sessions: null }, { sessions: { error: 'x' } },
    { sessions: SES({ mode: 'client', available: false, reason: 'r' }) }, { sessions: SES({ mode: 'client', available: false, enabled: true, reason: 'r' }) },
    { sessions: SES({ available: false, reason: 'r' }) },
    { sessions: SES() }, { sessions: SES(), sessionsPreviewed: true, sessionsPlan: 'p' },
    { sessions: SES({ enabled: true, waiting: { reason: 'r', since: 's' } }) }, { sessions: SES({ projects: [] }) }];
  for (const s of states) assert(!/[\u2013\u2014]/.test(ses(s)), JSON.stringify(s));
  const src = require('node:fs').readFileSync(require('node:path').join(__dirname, '../ui/settings-view.js'), 'utf8');
  const fn = src.slice(src.indexOf('function sessionSection'), src.indexOf('function importSection'));
  assert(fn.length > 100, 'sessionSection precedes importSection');
  assert(!/[\u2013\u2014]/.test(fn));
});

test('session capture never posts on its own', () => {
  assert.equal(sent.length, 0);
});

console.log(checks + ' settings view checks passed.');
