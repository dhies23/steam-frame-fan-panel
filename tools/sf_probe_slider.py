"""Probe a stock QAM slider (on the settings tab) and print its CSS vars.

  python tools/sf_probe_slider.py
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PROBE = open(os.path.join(HERE, "probe_slider_vars.js"), encoding="utf-8").read()

SELECT_SETTINGS = r"""
(() => {
  const t = document.getElementById('quickaccess_tab_4');
  if (!t) return 'no settings tab';
  const r = t.getBoundingClientRect();
  return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
})()
"""

BACK = r"""
(() => {
  const t = document.getElementById('sf_fan_tab');
  if (!t) return 'no fan tab';
  const r = t.getBoundingClientRect();
  return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
})()
"""


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
                time.sleep(1.5)

        pos = c.ev(SELECT_SETTINGS)
        print("settings tab:", pos)
        if pos and pos != 'no settings tab':
            x, y = json.loads(pos)
            c.click(x, y)
            time.sleep(1.5)

        print(c.ev(PROBE))

        pos = c.ev(BACK)
        if pos and pos != 'no fan tab':
            x, y = json.loads(pos)
            c.click(x, y)
            time.sleep(0.8)
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
