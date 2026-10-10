"""End-to-end test: drive the injected slider/toggle and verify pwm1 changes.

  python tools/sf_test_controls.py            # drag to 70%, then back to auto
  python tools/sf_test_controls.py --pwm 45
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf_refresh import CDP, bar, open_qam, popup  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def dev(cmd):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "frame", cmd],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return r.stdout.strip()


FAN_DIR = ("/sys/class/hwmon/$(for h in /sys/class/hwmon/hwmon*; do "
           "[ \"$(cat $h/name 2>/dev/null)\" = slg4ax46073v ] && basename $h; done)")


def fan_state():
    out = dev("D=%s; echo \"$(cat $D/pwm1) $(cat $D/fan1_input) "
              "$(systemctl is-active deckard-fan-control.service)\"" % FAN_DIR)
    try:
        pwm, fan, svc = out.split()
        return {"pwm": int(pwm), "rpm": int(fan) / 2.0, "service": svc}
    except Exception:
        return {"raw": out}


def slider_pos(c):
    r = c.ev("""(() => {
      const s = document.querySelector('#sf_fan_panel [role=slider]');
      if (!s) return null;
      const r = s.getBoundingClientRect();
      return JSON.stringify([r.x, r.y, r.width, r.height]);
    })()""")
    return json.loads(r) if r else None


def toggle_pos(c):
    r = c.ev("""(() => {
      const t = document.querySelector('#sf_fan_panel [role=checkbox]');
      if (!t) return null;
      const r = t.getBoundingClientRect();
      return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
    })()""")
    return json.loads(r) if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pwm", type=int, default=70)
    ap.add_argument("--keep-manual", action="store_true")
    args = ap.parse_args()

    print("before:", fan_state())

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

        # make sure our tab is selected
        r = c.ev("""(() => {
          const t = document.getElementById('sf_fan_tab');
          if (!t) return null;
          const r = t.getBoundingClientRect();
          return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
        })()""")
        if r:
            x, y = json.loads(r)
            c.click(x, y)
            time.sleep(1.0)

        rect = slider_pos(c)
        print("slider rect:", rect)
        if not rect:
            print("slider not found", file=sys.stderr)
            return 1
        sx, sy, sw, sh = rect
        target = sx + sw * (args.pwm / 100.0)
        ty = sy + sh / 2

        # drag: press at the left end, move to target, release
        c.call("Input.dispatchMouseEvent", {"type": "mouseMoved",
                                            "x": sx + 2, "y": ty, "buttons": 0})
        c.call("Input.dispatchMouseEvent", {"type": "mousePressed",
                                            "x": sx + 2, "y": ty,
                                            "button": "left", "buttons": 1,
                                            "clickCount": 1})
        for i in range(1, 11):
            x = sx + 2 + (target - sx - 2) * i / 10.0
            c.call("Input.dispatchMouseEvent", {"type": "mouseMoved",
                                                "x": x, "y": ty,
                                                "button": "left", "buttons": 1})
            time.sleep(0.05)
        c.call("Input.dispatchMouseEvent", {"type": "mouseReleased",
                                            "x": target, "y": ty,
                                            "button": "left", "buttons": 0,
                                            "clickCount": 1})
        time.sleep(2.0)

        print("after drag:", fan_state())
        st = c.ev("JSON.stringify(window.__SF_FAN__.getState())")
        print("panel state:", st)
        txt = c.ev("""(() => {
          const p = document.getElementById('sf_fan_body');
          return p ? p.innerText.replace(/\\n+/g, ' | ') : null;
        })()""")
        print("panel text:", txt)

        if not args.keep_manual:
            tp = toggle_pos(c)
            print("toggle at:", tp)
            if tp:
                x, y = tp
                c.click(x, y)
                time.sleep(2.0)
                print("after auto toggle:", fan_state())
                st = c.ev("JSON.stringify(window.__SF_FAN__.getState())")
                print("panel state:", st)
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
