"""Ensure the QAM is open with our fan tab selected, then dump the panel HTML.

  python tools/sf_refresh.py            # open QAM, select fan tab, dump panel
  python tools/sf_refresh.py --no-open  # assume QAM is already open
"""
import argparse
import json
import os
import sys
import time
import urllib.request

import websocket

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Where the GamepadUI CEF debug port is reachable from this machine.
# Either forward it (ssh -N -L 8081:127.0.0.1:8081 frame) or point this straight
# at the device: SF_CDP=192.168.1.129:8081
HOST = os.environ.get("SF_CDP", "127.0.0.1:8081")

QAM_OPEN_JS = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  if (root) {
    const r = root.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return 'open';
  }
  return 'closed';
})()
"""


def targets():
    with urllib.request.urlopen(f"http://{HOST}/json/list", timeout=10) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


class CDP:
    def __init__(self, url, timeout=15.0):
        self.ws = websocket.create_connection(url, timeout=timeout)
        self.ws.settimeout(timeout)
        self.i = 0

    def call(self, method, params=None):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method,
                                 "params": params or {}}))
        want = self.i
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == want:
                if "error" in r:
                    raise RuntimeError(f"{method}: {r['error']}")
                return r.get("result", {})

    def ev(self, expr):
        res = self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "userGesture": True})
        if res.get("exceptionDetails"):
            raise RuntimeError(json.dumps(res["exceptionDetails"],
                                          ensure_ascii=False)[:900])
        return res.get("result", {}).get("value")

    def click(self, x, y):
        for t, b in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.call("Input.dispatchMouseEvent", {
                "type": t, "x": x, "y": y, "button": "left",
                "buttons": b, "clickCount": 1, "pointerType": "mouse"})
            time.sleep(0.12)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def popup():
    for t in targets():
        if "barpopup" in t.get("title", ""):
            return t
    return None


def bar():
    for t in targets():
        if "gamepadui.bar (" in t.get("title", ""):
            return t
    return None


def open_qam(c):
    pos = c.ev(r"""
    (() => {
      const cands = [...document.querySelectorAll('[description],[aria-label]')];
      const b = cands.find(e => (e.getAttribute('description') || '') === '电源设置')
            || cands.find(e => /电量/.test(e.getAttribute('aria-label') || ''));
      if (!b) return null;
      const r = b.getBoundingClientRect();
      return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
    })()
    """)
    if not pos:
        return False
    x, y = json.loads(pos)
    c.click(x, y)
    time.sleep(2.5)
    return True


DUMP_JS = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  if (!root) return JSON.stringify({qamOpen: false});
  const panel = document.getElementById('sf_fan_panel');
  const tab = document.getElementById('sf_fan_tab');
  const tabbar = root.querySelector('[role="tablist"]');
  return JSON.stringify({
    qamOpen: true,
    tabPresent: !!tab,
    tabAria: tab ? tab.getAttribute('aria-selected') : null,
    panelPresent: !!panel,
    panelDisplay: panel ? getComputedStyle(panel).display : null,
    panelRect: panel ? (r => [Math.round(r.width), Math.round(r.height)])(panel.getBoundingClientRect()) : null,
    panelHTML: panel ? panel.outerHTML : null,
    tabHTML: tab ? tab.outerHTML : null,
    tabbarHTML: tabbar ? tabbar.outerHTML : null,
    rootCls: root.className,
    bodyCls: document.body.className,
    tabIds: [...root.querySelectorAll('[role=tab]')].map(t => t.id),
    state: window.__SF_FAN__ ? window.__SF_FAN__.getState() : null
  });
})()
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "shots", "panel_dump.json"))
    args = ap.parse_args()

    p = popup()
    if not p:
        print("barpopup target not found", file=sys.stderr)
        return 1
    c = CDP(p["webSocketDebuggerUrl"])
    try:
        if not args.no_open and c.ev(QAM_OPEN_JS) != 'open':
            b = bar()
            if b:
                cb = CDP(b["webSocketDebuggerUrl"])
                try:
                    open_qam(cb)
                finally:
                    cb.close()
            time.sleep(1.0)

        # select our tab
        r = c.ev("""(() => {
          const t = document.getElementById('sf_fan_tab');
          if (!t) return null;
          const r = t.getBoundingClientRect();
          return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
        })()""")
        if r:
            x, y = json.loads(r)
            c.click(x, y)
            time.sleep(1.2)

        dump = json.loads(c.ev(DUMP_JS))
    finally:
        c.close()

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=1)

    summary = {k: v for k, v in dump.items()
               if k not in ("panelHTML", "tabHTML", "tabbarHTML")}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("wrote", args.out)
    return 0 if dump.get("panelPresent") else 1


if __name__ == "__main__":
    sys.exit(main())
