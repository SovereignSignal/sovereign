/* Discovery describes evidence. Only service status describes a connection. */
window.SovDiscovery = (() => {
  const active = h => !!h && (h.state === 'connected' || h.declared || h.job_loaded || h.hook_registered || ['partial', 'removal incomplete'].includes(h.state));
  const current = status => !!status && !status.error && !status._status?.error && !status._status?.pending;
  function candidates(scan, status) {
    const harnesses = current(status) ? status.harnesses || [] : [];
    return (scan?.tools || []).map(tool => {
      const h = harnesses.find(h => h.id === tool.connector);
      const state = h?.state === 'connected' ? 'Connected' : active(h) ? 'Needs attention' : h?.state === 'removed' ? 'Removed' : tool.connector ? 'Available connector' : 'No connector yet';
      return {...tool, harness: h, active: active(h), state,
        found: tool.cloud ? 'Cloud service' : tool.installed ? 'App or command found' : tool.detected ? 'Saved configuration found' : 'No local installation found'};
    }).filter(t => t.detected || t.cloud || t.active || t.harness?.state === 'removed');
  }
  function filter(tools, query, category) {
    const q = query.trim().toLowerCase();
    return tools.filter(t => (!q || [t.name, ...(t.aliases || [])].join(' ').toLowerCase().includes(q)) &&
      (category === 'connected' ? t.active : category === 'available' ? t.connector && !t.active : category === 'unsupported' ? !t.connector : true));
  }
  return {active, current, candidates, filter};
})();
