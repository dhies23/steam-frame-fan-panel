"""Compare the geometry/style of the injected fan panel with a stock QAM tab.

Clicks the stock Settings tab, measures it, clicks the fan tab, measures it,
and reports whether the two are laid out identically.

  python tools/sf_compare_style.py
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

MEASURE = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  if (!root) return JSON.stringify({error: 'no qam'});

  const rect = el => {
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)];
  };
  const visible = el => {
    if (!el) return false;
    const b = el.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  };

  const bodies = [...root.querySelectorAll('[id^="quickaccess_content_"]')];
  const shownBody = bodies.find(b => visible(b.parentElement)) || null;
  const shownWrap = shownBody ? shownBody.parentElement : null;
  const fanPanel = document.getElementById('sf_fan_panel');
  const fanBody = document.getElementById('sf_fan_body');

  // the panel we are describing: the fan panel if it is showing, else stock
  const fanShowing = visible(fanPanel);
  const body = fanShowing ? fanBody : shownBody;
  const wrap = fanShowing ? fanPanel : shownWrap;
  const title = wrap ? wrap.firstElementChild : null;

  const rowLabel = body && body.querySelector('[id$="_Label"]');
  const section = body && body.querySelector(':scope > div > div');
  const valueNode = body && body.querySelector('[id$="_Label"] + div, [id$="_Label"] ~ div');

  const cs = el => el ? getComputedStyle(el) : null;
  const t = cs(title);
  const rl = cs(rowLabel);

  return JSON.stringify({
    fanShowing,
    bodyId: body ? body.id : null,
    wrapRect: rect(wrap),
    bodyRect: rect(body),
    bodyCls: body ? body.className : null,
    bodyPad: body ? cs(body).padding : null,
    bodyMaxWidth: body ? cs(body).maxWidth : null,
    bodyScroll: body ? [body.clientHeight, body.scrollHeight] : null,
    titleCls: title ? title.className : null,
    titleFont: t ? [t.fontSize, t.fontWeight, t.lineHeight] : null,
    titlePad: t ? t.padding : null,
    titleMargin: t ? t.margin : null,
    rowLabelH: rowLabel ? Math.round(rowLabel.getBoundingClientRect().height) : null,
    rowLabelFont: rl ? [rl.fontSize, rl.fontWeight, rl.lineHeight] : null,
    rowLabelColor: rl ? rl.color : null,
    rows: body ? [...body.querySelectorAll(':scope > div')].length : null
  }, null, 1);
})()
"""


def click_tab(c, tid):
    r = c.ev("""(() => { const t = document.getElementById('%s');
      if (!t) return null; const b = t.getBoundingClientRect();
      return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""" % tid)
    if not r:
        return False
    x, y = json.loads(r)
    c.click(x, y)
    time.sleep(1.4)
    return True


def main():
    p = popup()
    c = CDP(p["webSocketDebuggerUrl"])
    try:
        if not click_tab(c, "quickaccess_tab_4"):
            print("settings tab not found", file=sys.stderr)
            return 1
        stock = json.loads(c.ev(MEASURE))
        if not click_tab(c, "sf_fan_tab"):
            print("fan tab not found", file=sys.stderr)
            return 1
        ours = json.loads(c.ev(MEASURE))
    finally:
        c.close()

    keys = ["wrapRect", "bodyRect", "bodyPad", "bodyMaxWidth", "bodyScroll",
            "titleFont", "titlePad", "titleMargin", "rowLabelH", "rowLabelFont",
            "rowLabelColor"]
    print("%-14s | %-42s | %s" % ("field", "STOCK (settings tab)", "FAN TAB"))
    print("-" * 110)
    for k in keys:
        print("%-14s | %-42s | %s" % (k, stock.get(k), ours.get(k)))
    print()
    print("stock bodyCls:", stock.get("bodyCls"))
    print("fan   bodyCls:", ours.get("bodyCls"))
    print("stock titleCls:", stock.get("titleCls"))
    print("fan   titleCls:", ours.get("titleCls"))
    print()

    checks = [
        ("panel width matches",
         stock.get("wrapRect") and ours.get("wrapRect") and
         stock["wrapRect"][2] == ours["wrapRect"][2]),
        ("panel x matches",
         stock.get("wrapRect") and ours.get("wrapRect") and
         stock["wrapRect"][0] == ours["wrapRect"][0]),
        ("body padding matches", stock.get("bodyPad") == ours.get("bodyPad")),
        ("body max-width matches",
         stock.get("bodyMaxWidth") == ours.get("bodyMaxWidth")),
        ("title font matches", stock.get("titleFont") == ours.get("titleFont")),
        ("title padding matches", stock.get("titlePad") == ours.get("titlePad")),
        ("row label font matches",
         stock.get("rowLabelFont") == ours.get("rowLabelFont")),
        ("row label height matches",
         stock.get("rowLabelH") == ours.get("rowLabelH")),
        ("row label colour matches",
         stock.get("rowLabelColor") == ours.get("rowLabelColor")),
    ]
    bad = 0
    for name, ok in checks:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
        if not ok:
            bad += 1
    print("\n%d/%d style checks passed" % (len(checks) - bad, len(checks)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
