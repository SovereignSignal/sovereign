'use strict';
// One rail for both documents. Five destinations, each answering one question;
// Settings sits at the foot with the open archive. A page says where it is and
// what a destination means from there; the markup is the same everywhere.
window.SovShell = (() => {
  const NAV = [['today', 'Today'], ['review', 'Review'], ['sources', 'Sources'], ['library', 'Library'], ['backups', 'Backups']];
  const ICON = {
    today: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.2l2 1.3"/>',
    review: '<path d="M 3 8.5 l 3.2 3.2 L 13 4.8"/>',
    sources: '<circle cx="4" cy="4" r="1.6"/><circle cx="4" cy="12" r="1.6"/><circle cx="12" cy="8" r="1.6"/><path d="M 5.4 4.7 l 5.2 2.6 M 5.4 11.3 l 5.2 -2.6"/>',
    library: '<rect x="2.5" y="3" width="3" height="10" rx=".6"/><rect x="6.5" y="3" width="3" height="10" rx=".6"/><path d="M11.2 4.3l2.3-.6 2 8.2-2.3.6z"/>',
    backups: '<path d="M8 2l5 2v4c0 3-2.2 5-5 6-2.8-1-5-3-5-6V4z"/>',
    settings: '<circle cx="8" cy="8" r="2"/><path d="M8 2v2M8 12v2M2 8h2M12 8h2M3.8 3.8l1.4 1.4M10.8 10.8l1.4 1.4M12.2 3.8l-1.4 1.4M5.2 10.8l-1.4 1.4"/>',
  };
  const icon = k => `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;
  const tab = (k, label, extra = '') => `<button id="${k}-tab" data-nav="${k}" aria-pressed="false">${icon(k)}<span>${label}</span>${extra}</button>`;
  let rail = null;
  function mount(current, go) {
    rail = document.querySelector('.shell-rail');
    rail.innerHTML = `<div class="brand"><svg width="19" height="19" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M2 5.2 5.1 8.9 8 3.4l2.9 5.5L14 5.2l-.9 7.3H2.9L2 5.2zM3.1 13.2h9.8v1.2H3.1z"/></svg>Sovereign</div>`
      + NAV.map(([k, label]) => tab(k, label, k === 'review' ? '<span id="review-count"></span>' : '')).join('')
      + '<span class="sp"></span>' + tab('settings', 'Settings')
      + '<button id="change" title="Open another archive"><i class="dot"></i><span id="archive-name">Open archive…</span></button>';
    rail.addEventListener('click', e => { const b = e.target.closest('[data-nav]'); if (b) go(b.dataset.nav); });
    select(current);
  }
  function select(current) {
    if (rail) rail.querySelectorAll('[data-nav]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.nav === current)));
  }
  // The open archive, and whether the connected system answered for it.
  function archive(name, state) {
    if (!rail) return;
    rail.querySelector('#archive-name').textContent = name || 'Open archive…';
    rail.querySelector('#change .dot').className = 'dot ' + (state || '');
  }
  return { mount, select, archive };
})();
