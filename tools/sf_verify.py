"""Final end-to-end acceptance check for the QAM fan tab.

Verifies, against the live device, that:
  1. the fan tab exists in the QAM tablist, immediately after the "?" tab;
  2. activating it shows the panel (and hides the stock panels);
  3. the panel contains a speed slider, an auto toggle, live RPM, live duty
     cycle and live temperatures;
  4. dragging the slider actually changes pwm1 on the hardware;
  5. the auto toggle hands control back to deckard-fan-control.service.

  python tools/sf_verify.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf_refresh import CDP, bar, open_qam, popup  # noqa: E402
from sf_test_controls import fan_state  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -- " + detail) if detail else ""))


STRUCTURE = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  if (!root) return JSON.stringify({qamOpen: false});
  const tabs = [...root.querySelectorAll('[role="tablist"] [role="tab"]')];
  const ids = tabs.map(t => t.id);
  const fan = document.getElementById('sf_fan_tab');
  const help = document.getElementById('quickaccess_tab_6');
  const panel = document.getElementById('sf_fan_panel');
  const body = document.getElementById('sf_fan_body');
  const vis = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
  };
  const stockVisible = [...root.querySelectorAll('[id^="quickaccess_content_"]')]
    .filter(b => b.id !== 'sf_fan_body' && vis(b)).length;
  const r = el => { const b = el.getBoundingClientRect();
    return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)]; };
  const s = panel && panel.querySelector('[role="slider"]');
  const cb = panel && panel.querySelector('[role="checkbox"]');
  return JSON.stringify({
    qamOpen: true,
    tabIds: ids,
    fanIndex: ids.indexOf('sf_fan_tab'),
    helpIndex: ids.indexOf('quickaccess_tab_6'),
    tabAria: fan ? fan.getAttribute('aria-selected') : null,
    tabRect: fan ? r(fan) : null,
    helpRect: help ? r(help) : null,
    rootRect: r(root),
    panelVisible: vis(panel),
    panelRect: panel ? r(panel) : null,
    stockVisible,
    bodyScroll: body ? [body.clientHeight, body.scrollHeight] : null,
    hasSlider: !!s,
    sliderNow: s ? s.getAttribute('aria-valuenow') : null,
    hasToggle: !!cb,
    toggleChecked: cb ? cb.getAttribute('aria-checked') : null,
    text: body ? body.innerText.replace(/\n+/g, ' | ') : null,
    state: window.__SF_FAN__ ? window.__SF_FAN__.getState() : null,
    build: window.__SF_FAN__ ? window.__SF_FAN__.build : null
  });
})()
"""


def main():
    p = popup()
    if not p:
        print("barpopup target not found")
        return 1
    c = CDP(p["webSocketDebuggerUrl"])
    try:
        if c.ev("!!document.getElementById('QuickAccess-Menu')") is not True:
            b = bar()
            if b:
                cb = CDP(b["webSocketDebuggerUrl"])
                try:
                    open_qam(cb)
                finally:
                    cb.close()
                time.sleep(2.5)

        # select the fan tab
        r = c.ev("""(() => { const t = document.getElementById('sf_fan_tab');
          if (!t) return null; const b = t.getBoundingClientRect();
          return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""")
        if r:
            x, y = json.loads(r)
            c.click(x, y)
            time.sleep(1.2)

        d = json.loads(c.ev(STRUCTURE))
    finally:
        c.close()

    print("\n== 1. tab placement ==")
    check("QAM open", d.get("qamOpen"))
    check("fan tab in tablist", d.get("fanIndex", -1) >= 0,
          "tabIds=%s" % d.get("tabIds"))
    check("fan tab directly after the '?' help tab",
          d.get("fanIndex") == d.get("helpIndex", -2) + 1,
          "fanIndex=%s helpIndex=%s" % (d.get("fanIndex"), d.get("helpIndex")))
    check("fan tab selected", d.get("tabAria") == "true")
    tr, hr = d.get("tabRect"), d.get("helpRect")
    check("tab is the same size as the help tab",
          bool(tr and hr and tr[2:] == hr[2:]), "fan=%s help=%s" % (tr, hr))
    rr = d.get("rootRect")
    check("QAM is the stock 300x440 popup",
          bool(rr and rr[2:] == [300, 440]), "root=%s" % (rr,))

    print("\n== 2. panel ==")
    check("panel visible", d.get("panelVisible"))
    check("stock panels hidden while ours shows", d.get("stockVisible") == 0,
          "stockVisible=%s" % d.get("stockVisible"))
    check("panel matches QAM width", bool(d.get("panelRect") and
                                          d["panelRect"][2] == 299),
          "panel=%s" % (d.get("panelRect"),))
    check("panel scrolls when content overflows",
          bool(d.get("bodyScroll") and d["bodyScroll"][1] > d["bodyScroll"][0]),
          "body=%s" % (d.get("bodyScroll"),))

    print("\n== 3. controls and readouts ==")
    check("speed slider present", d.get("hasSlider"),
          "aria-valuenow=%s" % d.get("sliderNow"))
    check("auto toggle present", d.get("hasToggle"),
          "aria-checked=%s" % d.get("toggleChecked"))
    txt = d.get("text") or ""
    check("live RPM shown", "RPM" in txt)
    check("live duty cycle shown", "占空比" in txt)
    ntemps = sum(txt.count(k) for k in ("SoC", "CPU", "GPU", "内存", "散热片", "风扇口"))
    check("live temperatures shown (6 sensors)", ntemps >= 6, "found %d" % ntemps)
    st = d.get("state") or {}
    check("daemon is pushing state",
          st.get("rpm") is not None and st.get("pwm") is not None,
          "rpm=%s pwm=%s mode=%s" % (st.get("rpm"), st.get("pwm"), st.get("mode")))

    print("\n== 4. hardware: slider actually drives pwm1 ==")
    before = fan_state()
    print("  before:", before)
    p2 = popup()
    c = CDP(p2["webSocketDebuggerUrl"])
    try:
        r = c.ev("""(() => { const s = document.querySelector('#sf_fan_panel [role=slider]');
          if (!s) return null; const b = s.getBoundingClientRect();
          return JSON.stringify([b.x, b.y, b.width, b.height]); })()""")
        sx, sy, sw, sh = json.loads(r)
        target, ty = sx + sw * 0.80, sy + sh / 2
        c.call("Input.dispatchMouseEvent", {"type": "mouseMoved",
                                            "x": sx + 2, "y": ty, "buttons": 0})
        c.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx + 2,
                                            "y": ty, "button": "left",
                                            "buttons": 1, "clickCount": 1})
        for i in range(1, 9):
            x = sx + 2 + (target - sx - 2) * i / 8.0
            c.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x,
                                                "y": ty, "button": "left",
                                                "buttons": 1})
            time.sleep(0.05)
        c.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": target,
                                            "y": ty, "button": "left",
                                            "buttons": 0, "clickCount": 1})
        time.sleep(2.5)
    finally:
        c.close()
    after = fan_state()
    print("  after drag to 80%:", after)
    check("manual mode stops the stock controller",
          after.get("service") == "inactive", "service=%s" % after.get("service"))
    check("pwm1 changed and roughly matches the drag",
          isinstance(after.get("pwm"), int) and 65 <= after["pwm"] <= 85,
          "pwm1 %s -> %s" % (before.get("pwm"), after.get("pwm")))

    print("\n== 5. hardware: auto toggle restores stock control ==")
    p3 = popup()
    c = CDP(p3["webSocketDebuggerUrl"])
    try:
        mode_before = c.ev("window.__SF_FAN__.getState().mode")
        print("  panel mode before the click:", mode_before)
        r = c.ev("""(() => { const t = document.querySelector('#sf_fan_panel [role=checkbox]');
          if (!t) return null; const b = t.getBoundingClientRect();
          return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""")
        x, y = json.loads(r)
        c.click(x, y)
        time.sleep(3.0)
        mode_after = c.ev("window.__SF_FAN__.getState().mode")
        print("  panel mode after the click :", mode_after)
        checked = c.ev("document.querySelector('#sf_fan_panel [role=checkbox]')"
                       ".getAttribute('aria-checked')")
    finally:
        c.close()
    restored = fan_state()
    print("  after toggle:", restored, "aria-checked:", checked)
    check("stock controller running again",
          restored.get("service") == "active", "service=%s" % restored.get("service"))
    check("toggle reflects auto mode", checked == "true")

    print("\n== summary ==")
    print("  %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("  failed: %s" % ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
