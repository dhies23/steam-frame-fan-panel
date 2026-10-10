"""Dump every stock toggle row in the QAM settings tab, on and off, so the
visual difference between the two states can be diffed.

  python tools/dump_toggles.py
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

DUMP = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  if (!root) return JSON.stringify({open: false});
  const out = [];
  root.querySelectorAll('[role="checkbox"]').forEach(cb => {
    const row = cb.closest('[id$="_Label"]') ? cb.parentElement.parentElement
                                             : cb.parentElement;
    out.push({
      label: cb.getAttribute('aria-label'),
      checked: cb.getAttribute('aria-checked'),
      cbHTML: cb.outerHTML,
      rowHTML: row ? row.outerHTML : null
    });
  });
  return JSON.stringify({
    open: true,
    tab: (root.querySelector('[role=tab][aria-selected=true]') || {}).id,
    toggles: out
  });
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
                time.sleep(2.0)

        # remember what the user was looking at
        before = c.ev("(document.querySelector('#QuickAccess-Menu "
                      "[role=tab][aria-selected=true]')||{}).id")

        r = c.ev("""(() => { const t = document.getElementById('quickaccess_tab_4');
          if (!t) return null; const b = t.getBoundingClientRect();
          return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""")
        if r:
            c.click(*json.loads(r))
            time.sleep(1.5)

        dump = json.loads(c.ev(DUMP))

        # put the user's tab back
        if before:
            r = c.ev("""(() => { const t = document.getElementById('%s');
              if (!t) return null; const b = t.getBoundingClientRect();
              return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()"""
                     % before)
            if r:
                c.click(*json.loads(r))
                time.sleep(0.8)
    finally:
        c.close()

    with open(os.path.join(ROOT, "shots", "toggles.json"), "w",
              encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=1)

    for t in dump.get("toggles", []):
        print("%-28s checked=%-5s cbLen=%-6d rowLen=%d" % (
            (t.get("label") or "?")[:28], t.get("checked"),
            len(t.get("cbHTML") or ""), len(t.get("rowHTML") or "")))
    print("wrote shots/toggles.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
