"""Check the injected tab/panel survives QAM close/reopen and a QAM that
first opens on a tab with no slider/toggle rows (the template-harvest path).

  python tools/sf_test_reopen.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf_refresh import CDP, bar, open_qam, popup  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STATE = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  const r = el => { if (!el) return null; const b = el.getBoundingClientRect();
    return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)]; };
  const open = !!(root && (b => b.width > 0 && b.height > 0)(root.getBoundingClientRect()));
  const panel = document.getElementById('sf_fan_panel');
  const tab = document.getElementById('sf_fan_tab');
  const selected = root ? [...root.querySelectorAll('[role=tablist] [role=tab]')]
      .filter(t => t.getAttribute('aria-selected') === 'true').map(t => t.id) : [];
  return JSON.stringify({
    qamOpen: open,
    tabPresent: !!tab,
    panelPresent: !!panel,
    panelVisible: !!(panel && (b => b.width > 0 && b.height > 0)(panel.getBoundingClientRect())),
    panelRect: r(panel),
    rows: panel ? panel.querySelectorAll('[id$="_Label"]').length : 0,
    hasSlider: !!(panel && panel.querySelector('[role=slider]')),
    hasToggle: !!(panel && panel.querySelector('[role=checkbox]')),
    selected,
    tabIds: root ? [...root.querySelectorAll('[role=tablist] [role=tab]')].map(t => t.id) : []
  });
})()
"""


def click_id(c, tid):
    r = c.ev("""(() => { const t = document.getElementById('%s');
      if (!t) return null; const b = t.getBoundingClientRect();
      if (b.width === 0) return null;
      return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""" % tid)
    if not r:
        return False
    x, y = json.loads(r)
    c.click(x, y)
    time.sleep(1.2)
    return True


def battery_click():
    b = bar()
    cb = CDP(b["webSocketDebuggerUrl"])
    try:
        open_qam(cb)
    finally:
        cb.close()
    time.sleep(2.5)


def main():
    p = popup()
    c = CDP(p["webSocketDebuggerUrl"])
    try:
        if c.ev("!!document.getElementById('QuickAccess-Menu')") is not True:
            c.close()
            battery_click()
            c = CDP(popup()["webSocketDebuggerUrl"])

        print("A. switch to the Notifications tab (no slider/toggle rows)")
        click_id(c, "quickaccess_tab_0")
        print("  ", c.ev(STATE))
    finally:
        c.close()

    print("B. close the QAM, reopen it")
    battery_click()                      # close
    battery_click()                      # open again
    c = CDP(popup()["webSocketDebuggerUrl"])
    try:
        st = json.loads(c.ev(STATE))
        print("  ", json.dumps(st, ensure_ascii=False))
        print("C. click the fan tab")
        click_id(c, "sf_fan_tab")
        st2 = json.loads(c.ev(STATE))
        print("  ", json.dumps(st2, ensure_ascii=False))
    finally:
        c.close()

    ok = True
    for name, cond in [
        ("fan tab present after reopen", st.get("tabPresent")),
        ("panel present after reopen", st.get("panelPresent")),
        ("slider built", st.get("hasSlider")),
        ("toggle built", st.get("hasToggle")),
        ("all rows built", st.get("rows", 0) >= 10),
        ("panel visible after clicking the tab", st2.get("panelVisible")),
        ("fan tab selected", st2.get("selected") == ["sf_fan_tab"]),
    ]:
        print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
        ok &= bool(cond)
    print("\nresult:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
