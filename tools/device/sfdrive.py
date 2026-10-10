#!/usr/bin/env python3
"""Drive the fan panel from the device itself, the same way the UI does.

    python3 /tmp/sfdrive.py open
    python3 /tmp/sfdrive.py state
    python3 /tmp/sfdrive.py set_manual | set_auto | set_pwm 80
    python3 /tmp/sfdrive.py click_toggle        # real CDP mouse click
    python3 /tmp/sfdrive.py drag 80             # real CDP drag on the slider
    python3 /tmp/sfdrive.py key Right 5         # arrow-key steps
"""
import json
import sys
import time

sys.path.insert(0, "/home/steamos/sf-fan-qam")
import sf_fan_qamd as D  # noqa: E402

QAM_OPEN = r"""
(() => {
  const root = document.getElementById('QuickAccess-Menu');
  if (root) { const r = root.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return 'open'; }
  return 'closed';
})()
"""

BATTERY = r"""
(() => {
  const c = [...document.querySelectorAll('[description],[aria-label]')];
  const b = c.find(e => (e.getAttribute('description') || '') === '电源设置')
        || c.find(e => /电量/.test(e.getAttribute('aria-label') || ''));
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return JSON.stringify([r.x + r.width/2, r.y + r.height/2]);
})()
"""


def targets():
    return [t for t in D.http_json(D.CDP_HTTP + "/json/list")
            if t.get("type") == "page"]


def connect():
    url = D.find_target()
    if not url:
        raise SystemExit("QAM popup target not found")
    c = D.CDP(url)
    try:
        c.call("Runtime.addBinding", {"name": D.BINDING_NAME})
    except Exception:
        pass
    return c


def panel_visible(c):
    return c.evaluate(
        "(() => { const p = document.getElementById('sf_fan_panel');"
        " return !!p && p.getBoundingClientRect().width > 0; })()") is True


def ensure_panel(c=None, timeout=8.0):
    """Open the QAM if needed and select the fan tab so the panel has layout.

    Returns a connected client with the panel on screen, or None.
    """
    own = c is None
    if own:
        c = connect()
    try:
        if panel_visible(c):
            return c
        r = c.evaluate("""(() => {
          const t = document.getElementById('sf_fan_tab');
          if (!t) return null;
          const b = t.getBoundingClientRect();
          if (b.width <= 0) return null;
          return JSON.stringify([b.x + b.width/2, b.y + b.height/2]);
        })()""")
        if r:
            click(c, *json.loads(r))
            time.sleep(1.2)
        if panel_visible(c):
            return c
        if own:
            c.close()
            c = None
        if not open_qam():
            return None
        if own:
            c = connect()
        r = c.evaluate("""(() => {
          const t = document.getElementById('sf_fan_tab');
          if (!t) return null;
          const b = t.getBoundingClientRect();
          if (b.width <= 0) return null;
          return JSON.stringify([b.x + b.width/2, b.y + b.height/2]);
        })()""")
        if r:
            click(c, *json.loads(r))
            time.sleep(1.2)
        return c if panel_visible(c) else None
    except Exception:
        if own and c is not None:
            try:
                c.close()
            except Exception:
                pass
        raise


def click(c, x, y):
    for t, b in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
        c.call("Input.dispatchMouseEvent", {
            "type": t, "x": x, "y": y, "button": "left",
            "buttons": b, "clickCount": 1, "pointerType": "mouse"})


def slider_box(c):
    return rect(c, """(() => { const s = document.querySelector('#sf_fan_panel [role=slider]');
      if (!s) return null; const b = s.getBoundingClientRect();
      if (b.width <= 0) return null;
      return JSON.stringify([b.x, b.y + b.height/2, b.width]); })()""")


def drag_slider(c, target_pct, steps=8):
    """Drag the panel slider to target_pct with real CDP mouse events."""
    sx, ty, w = slider_box(c)
    tx = sx + w * target_pct / 100.0
    c.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx + 2,
                                        "y": ty, "button": "left",
                                        "buttons": 1, "clickCount": 1})
    for i in range(1, steps + 1):
        c.call("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": sx + 2 + (tx - sx - 2) * i / float(steps),
            "y": ty, "button": "left", "buttons": 1})
        time.sleep(0.05)
    c.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": tx,
                                        "y": ty, "button": "left",
                                        "buttons": 0, "clickCount": 1})
    time.sleep(0.12)


def send(c, cmd, value=None):
    msg = {"cmd": cmd}
    if value is not None:
        msg["value"] = value
    c.evaluate("__sfFanSend(%s)" % json.dumps(json.dumps(msg)))


def rect(c, js):
    r = c.evaluate(js)
    return json.loads(r) if r else None


def q(expr, default=None):
    return ("(() => { try { const v = (%s); return v === undefined ? null : v; }"
            " catch (e) { return null; } })()" % expr)


def show(c):
    print(json.dumps({
        "mode": c.evaluate(q("window.__SF_FAN__ && window.__SF_FAN__.getState().mode")),
        "aria": c.evaluate(q("document.querySelector('#sf_fan_panel [role=checkbox]')"
                             " && document.querySelector('#sf_fan_panel [role=checkbox]')"
                             ".getAttribute('aria-checked')")),
        "sliderVar": c.evaluate(q("document.querySelector('#sf_fan_panel [role=slider]')"
                                  " && document.querySelector('#sf_fan_panel [role=slider]')"
                                  ".style.getPropertyValue('--normalized-slider-value')")),
        "body": c.evaluate(q("document.querySelector('#sf_fan_panel')"
                             " && document.querySelector('#sf_fan_panel')"
                             ".innerText.replace(/\\n/g, ' | ')")),
        "qam": c.evaluate(QAM_OPEN),
    }, ensure_ascii=False, indent=1))


def open_qam():
    for t in targets():
        if "gamepadui.bar (" in (t.get("title") or ""):
            cb = D.CDP(t["webSocketDebuggerUrl"])
            try:
                if cb.evaluate(QAM_OPEN) == "open":
                    return True
                pos = cb.evaluate(BATTERY)
                if not pos:
                    return False
                click(cb, *json.loads(pos))
                time.sleep(2.5)
                return True
            finally:
                cb.close()
    return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    what = sys.argv[1]

    if what == "open":
        ok = open_qam()
        print("qam open:", ok)
        return 0 if ok else 1

    c = connect()
    try:
        if what in ("drag", "click_toggle", "diag", "step"):
            # make sure the panel is really on screen before touching it
            c = ensure_panel(c)
            if c is None:
                raise SystemExit("could not get the fan panel on screen")
        if what == "state":
            show(c)
        elif what in ("set_manual", "set_auto"):
            send(c, what)
        elif what == "set_pwm":
            send(c, "set_pwm", int(sys.argv[2]))
        elif what == "diag":
            # 1. record every binding call and every input event
            c.evaluate(r"""
            (() => {
              window.__diag = { sent: [], events: [] };
              if (!window.__origSend) {
                window.__origSend = window.__sfFanSend;
                window.__sfFanSend = function (p) {
                  window.__diag.sent.push(p);
                  return window.__origSend(p);
                };
              }
              ['pointerdown','pointermove','pointerup','mousedown','mouseup',
               'click','keydown'].forEach(t => window.addEventListener(t, ev => {
                 if (t === 'pointermove' && window.__diag.events.filter(
                       e => e.t === 'pointermove').length > 2) return;
                 const el = ev.target;
                 window.__diag.events.push({
                   t: t, x: Math.round(ev.clientX || 0), y: Math.round(ev.clientY || 0),
                   tag: el && el.tagName, role: el && el.getAttribute
                         && el.getAttribute('role'),
                   inPanel: !!(el && el.closest && el.closest('#sf_fan_panel'))
                 });
               }), true);
              return 'ok';
            })()
            """)
            p = rect(c, """(() => { const s = document.querySelector('#sf_fan_panel [role=slider]');
              if (!s) return null; const b = s.getBoundingClientRect();
              const row = s.closest('[role=button]');
              return JSON.stringify({slider: [b.x, b.y, b.width, b.height],
                group: row ? row.getBoundingClientRect().width : null,
                groupIsSlider: row === s,
                hasBinding: typeof window.__sfFanSend === 'function',
                build: window.__SF_FAN__ && window.__SF_FAN__.build}); })()""")
            print("slider:", json.dumps(p))
            c.evaluate("window.__diag.sent = []; window.__diag.events = []")
            sx, sy, w, h = p["slider"]
            if w <= 0 or h <= 0:
                raise SystemExit("slider has no layout (QAM closed?)")
            ty = sy + h / 2
            tx = sx + w * 0.8
            c.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx + 2,
                                                "y": ty, "button": "left",
                                                "buttons": 1, "clickCount": 1})
            for i in range(1, 6):
                c.call("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": sx + 2 + (tx - sx - 2) * i / 5.0,
                    "y": ty, "button": "left", "buttons": 1})
                time.sleep(0.08)
            c.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": tx,
                                                "y": ty, "button": "left",
                                                "buttons": 0, "clickCount": 1})
            time.sleep(1.0)
            print("events:", c.evaluate("JSON.stringify(window.__diag.events)"))
            print("binding calls:", c.evaluate("JSON.stringify(window.__diag.sent)"))
        elif what == "step":
            # dispatch one CDP mouse event at a time and see what lands
            c.evaluate(r"""
            (() => {
              window.__step = [];
              ['pointerdown','pointermove','pointerup','mousedown','mouseup','click']
                .forEach(t => window.addEventListener(t, ev => {
                  const el = ev.target;
                  window.__step.push(t + '@' + Math.round(ev.clientX) + ',' +
                    Math.round(ev.clientY) + ' ' + (el && el.tagName) + ' in=' +
                    !!(el && el.closest && el.closest('#sf_fan_panel')));
                }, true));
              return 'ok';
            })()
            """)
            p = rect(c, """(() => { const s = document.querySelector('#sf_fan_panel [role=slider]');
              if (!s) return null; const b = s.getBoundingClientRect();
              return JSON.stringify({slider: [b.x, b.y, b.width, b.height],
                at: (document.elementFromPoint(b.x + b.width*0.5, b.y + b.height/2)||{})
                     .className,
                hitRole: (document.elementFromPoint(b.x + b.width*0.5, b.y + b.height/2)||{})
                     .getAttribute && document.elementFromPoint(b.x + b.width*0.5,
                     b.y + b.height/2).getAttribute('role')}); })()""")
            sx, sy, w, h = p["slider"]
            ty = sy + h / 2
            print("slider", [sx, sy, w, h], "elementFromPoint cls:", p["at"],
                  "role:", p["hitRole"])

            def dump(tag):
                print(" ", tag, c.evaluate("JSON.stringify(window.__step)"))

            c.evaluate("window.__step = []")
            c.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sx + 4,
                                                "y": ty, "buttons": 0})
            time.sleep(0.4); dump("after mouseMoved(hover)")

            c.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx + 4,
                                                "y": ty, "button": "left",
                                                "buttons": 1, "clickCount": 1})
            time.sleep(0.4); dump("after mousePressed")

            c.call("Input.dispatchMouseEvent", {"type": "mouseMoved",
                                                "x": sx + w * 0.5, "y": ty,
                                                "button": "left", "buttons": 1})
            time.sleep(0.4); dump("after mouseMoved(drag)")

            c.call("Input.dispatchMouseEvent", {"type": "mouseReleased",
                                                "x": sx + w * 0.5, "y": ty,
                                                "button": "left", "buttons": 0,
                                                "clickCount": 1})
            time.sleep(0.6); dump("after mouseReleased")
            print("  binding calls:",
                  c.evaluate("window.__diag ? JSON.stringify(window.__diag.sent) : 'n/a'"))
            show(c)
        elif what == "click_toggle":
            p = rect(c, """(() => { const t = document.querySelector('#sf_fan_panel [role=checkbox]');
              if (!t) return null; const b = t.getBoundingClientRect();
              return JSON.stringify([b.x + b.width/2, b.y + b.height/2]); })()""")
            if not p:
                raise SystemExit("toggle not found (QAM closed?)")
            click(c, *p)
        elif what == "drag":
            drag_slider(c, int(sys.argv[2]))
        else:
            raise SystemExit("unknown: %s" % what)
    finally:
        c.close()
    time.sleep(0.4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
