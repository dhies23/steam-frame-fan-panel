"""Regression tests for the two faults reported from the headset:

  1. the manual slider "only worked for a moment" and sometimes dropped the fan
     to 0 -- a collapsed slider read as 0 % and the stock controller could come
     back underneath us;
  2. the auto-thermostat toggle "did nothing" when clicked -- it flipped state
     and flipped straight back because the daemon polls at 1 Hz.

Checks, all against the real hardware:

  A. the toggle responds to the first click, and keeps responding to every
     later click (auto -> manual -> auto -> manual);
  B. a manual duty cycle is still in pwm1 fifteen seconds later, and non-zero;
  C. dragging the slider to the far left never commands 0 -- the floor holds;
  D. auto really hands the fan back to deckard-fan-control.service;
  E. the numbers on screen really are live: the rendered RPM follows the kernel
     tach, and the panel adds only a fraction of a second on top of the ~3 s the
     fan controller itself needs to latch a new reading.

  python tools/sf_test_regress.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf_refresh import CDP, bar, open_qam, popup  # noqa: E402
from sf_test_controls import fan_state, dev, FAN_DIR  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -- " + str(extra)) if extra else ""))


def toggle_pos(c):
    r = c.ev("""(() => {
      const t = document.querySelector('#sf_fan_panel [role=checkbox]');
      if (!t) return null;
      const b = t.getBoundingClientRect();
      return JSON.stringify([b.x + b.width/2, b.y + b.height/2]);
    })()""")
    return json.loads(r) if r else None


def slider_rect(c):
    r = c.ev("""(() => {
      const s = document.querySelector('#sf_fan_panel [role=slider]');
      if (!s) return null;
      const b = s.getBoundingClientRect();
      return JSON.stringify([b.x, b.y, b.width, b.height]);
    })()""")
    return json.loads(r) if r else None


def panel_mode(c):
    return c.ev("window.__SF_FAN__ && window.__SF_FAN__.getState().mode")


def drag(c, frac):
    """Drag the slider to `frac` of its width (0 = far left, 1 = far right)."""
    sx, sy, sw, sh = slider_rect(c)
    ty = sy + sh / 2
    tx = sx + sw * frac
    c.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sx + 2,
                                        "y": ty, "buttons": 0})
    c.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx + 2,
                                        "y": ty, "button": "left",
                                        "buttons": 1, "clickCount": 1})
    for i in range(1, 9):
        c.call("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": sx + 2 + (tx - sx - 2) * i / 8.0,
            "y": ty, "button": "left", "buttons": 1})
        time.sleep(0.05)
    c.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": tx,
                                        "y": ty, "button": "left",
                                        "buttons": 0, "clickCount": 1})


def read_row(c):
    """The RPM number as it is actually rendered on the panel.

    A row is  <row><labelHolder><label/></labelHolder><control/></row>, with a
    couple of single-child wrappers in between. Walk up from the label until an
    ancestor has more than one element child; the control slot is its last one.
    """
    return c.ev("""(() => {
      const p = document.getElementById('sf_fan_panel');
      if (!p) return null;
      for (const l of p.querySelectorAll('[id$="_Label"]')) {
        if ((l.textContent || '').indexOf('实时转速') >= 0) {
          let n = l;
          while (n.parentElement && n.parentElement.children.length < 2) {
            n = n.parentElement;
          }
          const slot = n.parentElement && n.parentElement.lastElementChild;
          return slot ? slot.textContent : null;
        }
      }
      return null;
    })()""")


def tach_raw():
    out = dev("D=%s; cat $D/fan1_input" % FAN_DIR)
    try:
        return int(out)
    except ValueError:
        return None


def focus_panel(c):
    r = c.ev("""(() => {
      const t = document.getElementById('sf_fan_tab');
      if (!t) return null;
      const b = t.getBoundingClientRect();
      if (b.width <= 0) return null;
      return JSON.stringify([b.x + b.width/2, b.y + b.height/2]);
    })()""")
    if r:
        c.click(*json.loads(r))
        time.sleep(1.2)


def open_if_needed(c):
    if c.ev("!!document.getElementById('QuickAccess-Menu')") is True:
        return
    b = bar()
    if not b:
        return
    cb = CDP(b["webSocketDebuggerUrl"])
    try:
        open_qam(cb)
    finally:
        cb.close()
    time.sleep(2.0)


def main():
    p = popup()
    if not p:
        print("barpopup target not found", file=sys.stderr)
        return 1
    c = CDP(p["webSocketDebuggerUrl"])
    try:
        open_if_needed(c)
        focus_panel(c)

        # ---------------------------------------------------------------
        print("\n== A. the toggle answers every click ==")
        # start from a known auto state
        c.ev("window.__SF_FAN__.setState({mode: 'auto'})")
        for _ in range(20):
            if fan_state().get("service") == "active":
                break
            time.sleep(0.5)
        want = ["manual", "auto", "manual"]
        for i, expect in enumerate(want, 1):
            tp = toggle_pos(c)
            if not tp:
                check("toggle found (click %d)" % i, False)
                break
            c.click(*tp)
            time.sleep(2.2)
            got = panel_mode(c)
            svc = fan_state().get("service")
            check("click %d -> %s" % (i, expect), got == expect,
                  "panel says %s" % got)
            check("click %d -> stock controller %s" % (
                i, "stopped" if expect == "manual" else "running"),
                svc == ("inactive" if expect == "manual" else "active"),
                "service=%s" % svc)

        # ---------------------------------------------------------------
        print("\n== B. a manual setting survives ==")
        drag(c, 0.80)
        time.sleep(2.0)
        first = fan_state()
        print("  right after the drag:", first)
        time.sleep(15.0)
        later = fan_state()
        print("  15 s later:", later)
        check("manual duty cycle is non-zero", first.get("pwm", 0) > 0,
              "pwm=%s" % first.get("pwm"))
        check("pwm1 is unchanged 15 s later",
              first.get("pwm") == later.get("pwm"),
              "%s -> %s" % (first.get("pwm"), later.get("pwm")))
        check("the stock controller stayed away",
              later.get("service") == "inactive",
              "service=%s" % later.get("service"))
        check("the panel still reports manual", panel_mode(c) == "manual",
              panel_mode(c))

        # ---------------------------------------------------------------
        print("\n== C. the far-left end never stops the fan ==")
        drag(c, 0.0)
        time.sleep(2.5)
        low = fan_state()
        print("  after dragging fully left:", low)
        check("pwm1 did not fall to 0", low.get("pwm", 0) > 0,
              "pwm=%s" % low.get("pwm"))
        check("pwm1 respects the manual floor (>= 20)",
              low.get("pwm", 0) >= 20, "pwm=%s" % low.get("pwm"))
        check("the fan is still spinning", low.get("rpm", 0) > 200,
              "rpm=%s" % low.get("rpm"))

        # ---------------------------------------------------------------
        print("\n== D. auto hands the fan back ==")
        tp = toggle_pos(c)
        c.click(*tp)
        time.sleep(3.0)
        back = fan_state()
        print("  after switching back to auto:", back)
        check("stock controller running again",
              back.get("service") == "active", "service=%s" % back.get("service"))
        check("panel reports auto", panel_mode(c) == "auto", panel_mode(c))

        # ---------------------------------------------------------------
        print("\n== E. the numbers on screen are live ==")
        drag(c, 0.30)
        time.sleep(9.0)
        samples = []
        t0 = time.time()
        while time.time() - t0 < 18.0:
            samples.append((time.time() - t0, tach_raw(), read_row(c)))
            time.sleep(0.25)

        def changes(idx):
            out = []
            for i, s in enumerate(samples):
                if i == 0 or s[idx] != samples[i - 1][idx]:
                    out.append((s[0], s[idx]))
            return out

        tach_ch = [x for x in changes(1) if x[1] is not None]
        row_ch = [x for x in changes(2) if x[1]]
        gap = None
        if len(tach_ch) > 1:
            gap = (tach_ch[-1][0] - tach_ch[0][0]) / (len(tach_ch) - 1)
        print("  kernel tach changes : %d%s" % (
            len(tach_ch), "  (one every ~%.1f s)" % gap if gap else ""))
        print("  on-screen changes   : %d" % len(row_ch))

        lags = []
        for t, raw in tach_ch:
            want = "%.0f RPM" % round(raw / 2.0)
            for t2, txt in row_ch:
                if t2 >= t and txt == want:
                    lags.append(t2 - t)
                    break
        check("the rendered number tracks the kernel tach",
              len(lags) >= 2, "%d of %d samples matched" % (len(lags), len(tach_ch)))
        if lags:
            worst = max(lags)
            check("the panel adds under a second on top of the tach",
                  worst < 1.0, "worst %.2f s" % worst)
            print("  lag tach -> pixels  : min %.2f s, median %.2f s, max %.2f s"
                  % (min(lags), sorted(lags)[len(lags) // 2], worst))
        check("the readout is not frozen",
              len(row_ch) >= 2, "%d on-screen updates in 18 s" % len(row_ch))

        tp = toggle_pos(c)
        c.click(*tp)
        time.sleep(3.0)
    finally:
        c.close()

    print("\n== summary ==")
    print("  %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("  failed: %s" % ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
