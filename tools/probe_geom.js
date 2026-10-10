(() => {
  const root = document.getElementById('QuickAccess-Menu');
  if (!root) return 'no qam';
  const r = el => {
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)];
  };
  const panel = document.getElementById('sf_fan_panel');
  const body = document.getElementById('sf_fan_body');
  const tab = document.getElementById('sf_fan_tab');
  const tabbar = root.querySelector('[role="tablist"]');
  const stock = [...root.querySelectorAll('[id^="quickaccess_content_"]')]
    .filter(b => b.id !== 'sf_fan_body');
  const out = {
    root: r(root),
    tabbar: r(tabbar),
    tab: r(tab),
    panel: r(panel),
    body: r(body),
    bodyScroll: body ? [body.clientHeight, body.scrollHeight] : null,
    panelScroll: panel ? [panel.clientHeight, panel.scrollHeight] : null,
    stockBody: stock.length ? r(stock[0]) : null,
    stockScroll: stock.length ? [stock[0].clientHeight, stock[0].scrollHeight] : null,
    bodyCls: body ? body.className : null
  };
  return JSON.stringify(out, null, 1);
})()
