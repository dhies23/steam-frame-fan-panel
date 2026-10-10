"""Cold-start test without reloading the CEF page.

A page reload wipes the injected overlay document and Steam does not recreate
it until the web helper restarts, so this test simulates a cold start the way
it actually happens in the field:

  1. clear the cached row templates;
  2. switch the QAM to a tab that renders no slider/toggle rows;
  3. drop the injected UI (teardown) and let the daemon re-inject;
  4. confirm the harvest fallback rebuilds the tab and panel from scratch.

  python tools/sf_test_coldstart.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf_refresh import CDP, popup  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STATE = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  const vis = el => !!(el && (b => b.width > 0 && b.height > 0)(el.getBoundingClientRect()));
  const panel = document.getElementById('sf_fan_panel');
  const body = document.getElementById('sf_fan_body');
  return JSON.stringify({
    qamOpen: vis(root),
    injected: !!window.__SF_FAN__,
    build: window.__SF_FAN__ ? window.__SF_FAN__.build : null,
    cached: (() => { try { return !!sessionStorage.getItem('sf_fan_tpl_v3'); }
                     catch (e) { return 'n/a'; } })(),
    tabPresent: !!document.getElementById('sf_fan_tab'),
    panelPresent: !!panel,
    panelVisible: vis(panel),
    rows: panel ? panel.querySelectorAll('[id$="_Label"]').length : 0,
    hasSlider: !!(panel && panel.querySelector('[role=slider]')),
    hasToggle: !!(panel && panel.querySelector('[role=checkbox]')),
    selected: root ? [...root.querySelectorAll('[role=tablist] [role=tab]')]
      .filter(t => t.getAttribute('aria-selected') === 'true').map(t => t.id) : [],
    text: body ? body.innerText.replace(/\n+/g, ' | ').slice(0, 140) : null
  });
})()
"""


def state(c):
    return json.loads(c.ev(STATE))


def click_id(c, tid, settle=1.4):
    r = c.ev("""(() => { const t = document.getElementById('%s');
      if (!t) return null; const b = t.getBoundingClientRect();
      if (!b.width) return null;
      return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""" % tid)
    if not r:
        return False
    x, y = json.loads(r)
    c.click(x, y)
    time.sleep(settle)
    return True


def main():
    c = CDP(popup()["webSocketDebuggerUrl"])
    try:
        st = state(c)
        if not st["qamOpen"]:
            print("QAM is not open; run tools/sf_refresh.py first", file=sys.stderr)
            return 1
        print("start:", json.dumps(st, ensure_ascii=False))

        print("\n1. select the Notifications tab (no slider/toggle rows)")
        click_id(c, "quickaccess_tab_0")
        print("   ", json.dumps(state(c), ensure_ascii=False))

        print("\n2. clear the template cache and drop the injected UI in one go")
        c.ev("(function(){ try{sessionStorage.removeItem('sf_fan_tpl_v3')}"
             "catch(e){}; window.__SF_FAN__.teardown(); return 'ok'; })()")
        time.sleep(0.4)
        print("   ", json.dumps(state(c), ensure_ascii=False))
    finally:
        c.close()

    print("\n3. wait for the daemon to re-inject and harvest templates")
    for i in range(20):
        time.sleep(1)
        c = CDP(popup()["webSocketDebuggerUrl"])
        try:
            st = state(c)
        finally:
            c.close()
        if st["tabPresent"] and st["panelPresent"]:
            break
    print("   after %ds:" % (i + 1), json.dumps(st, ensure_ascii=False))

    print("\n4. click the fan tab")
    c = CDP(popup()["webSocketDebuggerUrl"])
    try:
        click_id(c, "sf_fan_tab", 1.8)
        st2 = state(c)
    finally:
        c.close()
    print("   ", json.dumps(st2, ensure_ascii=False))

    checks = [
        ("daemon re-injected", st["injected"]),
        ("templates re-harvested and cached", st["cached"] is True),
        ("fan tab rebuilt", st["tabPresent"]),
        ("panel rebuilt", st["panelPresent"]),
        ("all rows built", st.get("rows", 0) >= 10),
        ("slider built", st["hasSlider"]),
        ("toggle built", st["hasToggle"]),
        ("panel shows when the tab is clicked", st2["panelVisible"]),
        ("fan tab selected", st2["selected"] == ["sf_fan_tab"]),
        ("live text rendered", bool(st2.get("text") and "RPM" in st2["text"])),
    ]
    bad = 0
    for name, ok in checks:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
        bad += 0 if ok else 1
    print("\n%d/%d passed" % (len(checks) - bad, len(checks)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
