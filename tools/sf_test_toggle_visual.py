"""The toggle must *look* different after every click.

Steam's Toggle shows its state through one class on the checkbox element (the
knob slides, the track turns blue); nothing in the stylesheet keys off
aria-checked. So this checks the thing the user actually sees: the class, and
the resolved transform of the knob.

  python tools/sf_test_toggle_visual.py
"""
import json
import os
import re
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


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -- " + str(extra)) if extra else ""))


LOOK = r"""
(() => {
  const panel = document.getElementById('sf_fan_panel');
  if (!panel) return JSON.stringify({panel: false});
  const cb = panel.querySelector('[role=checkbox]');
  if (!cb) return JSON.stringify({panel: true, cb: false});
  const knob = cb.children[1];
  const rail = cb.children[0];
  const t = window.__SF_FAN__ && window.__SF_FAN__.getState();
  return JSON.stringify({
    panel: true, cb: true,
    aria: cb.getAttribute('aria-checked'),
    cls: cb.className,
    knobTransform: knob ? getComputedStyle(knob).transform : null,
    railBefore: rail ? getComputedStyle(rail, '::before').transform : null,
    mode: t ? t.mode : null,
    onExtra: (window.__SF_FAN__ && window.__SF_FAN__.tpl)
             ? window.__SF_FAN__.tpl.toggleOnExtra : null,
    tpl: {
      onExtra: !!(window.__SF_FAN__ && window.__SF_FAN__.tpl &&
                  window.__SF_FAN__.tpl.toggleOnExtra),
      onHTML: !!(window.__SF_FAN__ && window.__SF_FAN__.tpl &&
                 window.__SF_FAN__.tpl.toggleOnHTML),
      offHTML: !!(window.__SF_FAN__ && window.__SF_FAN__.tpl &&
                  window.__SF_FAN__.tpl.toggleOffHTML)
    }
  });
})()
"""


def toggle_pos(c):
    r = c.ev("""(() => {
      const t = document.querySelector('#sf_fan_panel [role=checkbox]');
      if (!t) return null;
      const b = t.getBoundingClientRect();
      return JSON.stringify([b.x + b.width/2, b.y + b.height/2]);
    })()""")
    return json.loads(r) if r else None


def main():
    p = popup()
    if not p:
        print("barpopup not found", file=sys.stderr)
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
                time.sleep(2.0)

        r = c.ev("""(() => { const t = document.getElementById('sf_fan_tab');
          if (!t) return null; const b = t.getBoundingClientRect();
          return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""")
        if r:
            c.click(*json.loads(r))
            time.sleep(1.2)

        first = json.loads(c.ev(LOOK))
        print("  templates:", first.get("tpl"))
        check("toggle-state class was harvested",
              first["tpl"]["onExtra"], first["tpl"])

        # walk through the states and record how it looks each time
        seen = []
        for i in range(4):
            st = json.loads(c.ev(LOOK))
            seen.append((st["mode"], st["aria"], st["cls"], st["knobTransform"]))
            print("  state %d: mode=%-6s aria=%-5s knob=%s\n            cls=%s"
                  % (i, st["mode"], st["aria"], st["knobTransform"], st["cls"]))
            tp = toggle_pos(c)
            if not tp:
                check("toggle reachable (round %d)" % i, False)
                break
            c.click(*tp)
            time.sleep(2.0)
        st = json.loads(c.ev(LOOK))
        seen.append((st["mode"], st["aria"], st["cls"], st["knobTransform"]))
        print("  state %d: mode=%-6s aria=%-5s knob=%s\n            cls=%s"
              % (len(seen) - 1, st["mode"], st["aria"], st["knobTransform"],
                 st["cls"]))

        modes = [s[0] for s in seen]
        knobs = [s[3] for s in seen]

        def tx(t):
            """The horizontal offset of the knob, whatever form it comes in."""
            if not t or t == "none":
                return 0.0
            m = re.match(r"matrix\(([^)]*)\)", t)
            if m:
                parts = [float(p) for p in m.group(1).split(",")]
                return parts[4] if len(parts) == 6 else 0.0
            m = re.match(r"translateX\((-?[\d.]+)px\)", t)
            return float(m.group(1)) if m else 0.0

        xs = [tx(k) for k in knobs]
        check("the mode alternates on every click",
              modes == ["auto", "manual", "auto", "manual", "auto"], modes)
        check("the knob sits in two distinct positions",
              len(set(xs)) == 2, knobs)
        check("the knob is right exactly when auto",
              [x > 0 for x in xs] == [m == "auto" for m in modes],
              "%s -> %s" % (xs, [m == "auto" for m in modes]))
        extra = first.get("onExtra")
        check("the on-class is present exactly while auto",
              [extra in s[2] for s in seen] == [m == "auto" for m in modes],
              "%s -> %s" % (extra, [extra in s[2] for s in seen]))
        check("aria-checked tracks the mode",
              [s[1] for s in seen] == ["true", "false", "true", "false", "true"],
              [s[1] for s in seen])
    finally:
        c.close()

    print("\n== hardware ==")
    print("  fan now:", fan_state())
    print("\n== summary ==")
    print("  %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("  failed: %s" % ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
