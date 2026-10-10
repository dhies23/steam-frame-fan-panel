"""Click the auto-thermostat toggle in auto mode and confirm manual takeover
holds the current duty cycle (no speed jump).  Then restore auto.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf_refresh import CDP, popup  # noqa: E402
from sf_test_controls import fan_state  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def toggle_pos(c):
    r = c.ev("""(() => {
      const t = document.querySelector('#sf_fan_panel [role=checkbox]');
      if (!t) return null;
      const r = t.getBoundingClientRect();
      return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
    })()""")
    return json.loads(r) if r else None


def main():
    p = popup()
    c = CDP(p["webSocketDebuggerUrl"])
    try:
        print("start:", fan_state())
        tp = toggle_pos(c)
        if not tp:
            print("no toggle", file=sys.stderr)
            return 1
        x, y = tp
        c.click(x, y)
        time.sleep(2.5)
        print("after toggle -> manual:", fan_state())
        print("state:", c.ev("JSON.stringify(window.__SF_FAN__.getState())"))
        print("aria-checked:",
              c.ev("document.querySelector('#sf_fan_panel [role=checkbox]')"
                   ".getAttribute('aria-checked')"))

        c.click(x, y)
        time.sleep(2.5)
        print("after toggle -> auto:", fan_state())
        print("aria-checked:",
              c.ev("document.querySelector('#sf_fan_panel [role=checkbox]')"
                   ".getAttribute('aria-checked')"))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
