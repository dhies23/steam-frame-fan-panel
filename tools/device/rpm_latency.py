"""Watch the RPM number travel from the kernel to the pixels.

Samples three things on one clock for N seconds:
  * the raw sysfs tach,
  * what the daemon last pushed into the page (state.rpm),
  * the text actually rendered in the 实时转速 row.

    python3 /tmp/rpm_latency.py [seconds]
"""
import json
import os
import sys
import time

sys.path.insert(0, "/home/steamos/sf-fan-qam")
sys.path.insert(0, "/tmp")
import sf_fan_qamd as D  # noqa: E402
import sfdrive  # noqa: E402

PROBE = r"""
(() => {
  const p = document.getElementById('sf_fan_panel');
  if (!p) return 'NOPANEL';
  const A = window.__SF_FAN__;
  const st = A && A.getState ? A.getState() : {};
  let row = 'NOROW';
  for (const l of p.querySelectorAll('[id$="_Label"]')) {
    if ((l.textContent || '').indexOf('实时转速') >= 0) {
      const kids = l.parentElement.querySelectorAll('div');
      row = kids.length ? kids[kids.length - 1].textContent : 'NOVALUE';
    }
  }
  return JSON.stringify({row: row, rpm: st.rpm, pwm: st.pwm, mode: st.mode});
})()
"""


def fan_dir():
    base = "/sys/class/hwmon"
    for h in sorted(os.listdir(base)):
        p = os.path.join(base, h)
        try:
            if open(os.path.join(p, "name")).read().strip() == "slg4ax46073v":
                return p
        except Exception:
            pass
    raise SystemExit("fan hwmon not found")


def ensure_panel():
    c = D.CDP(D.find_target())
    try:
        if c.evaluate("!!document.getElementById('sf_fan_panel')"):
            return True
    finally:
        c.close()
    if not sfdrive.open_qam():
        return False
    c = sfdrive.connect()
    try:
        r = c.evaluate("""(() => {
          const t = document.getElementById('sf_fan_tab');
          if (!t) return null;
          const b = t.getBoundingClientRect();
          if (b.width <= 0) return null;
          return JSON.stringify([b.x + b.width/2, b.y + b.height/2]);
        })()""")
        if r:
            sfdrive.click(c, *json.loads(r))
            time.sleep(1.2)
        return bool(c.evaluate("!!document.getElementById('sf_fan_panel')"))
    finally:
        c.close()


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    tach = os.path.join(fan_dir(), "fan1_input")

    if not ensure_panel():
        print("could not get the fan panel on screen")
        return 1

    c = D.CDP(D.find_target())
    rows = []
    try:
        t0 = time.time()
        while time.time() - t0 < dur:
            raw = int(open(tach).read())
            try:
                probe = json.loads(c.evaluate(PROBE))
            except Exception as e:
                probe = {"row": "ERR:%s" % e, "rpm": None}
            rows.append((time.time() - t0, raw, raw / 2.0, probe))
            time.sleep(0.2)
    finally:
        c.close()

    print("  t(s)   kernel   rpmK     state.rpm   row")
    last = None
    for t, raw, rpm, p in rows:
        key = (raw, p.get("rpm"), p.get("row"))
        mark = ""
        if key != last:
            mark = "  <-- change"
            last = key
        print("  %5.2f  %7d  %7.1f   %-10s  %-12s%s"
              % (t, raw, rpm, p.get("rpm"), p.get("row"), mark))

    def trans(idx):
        out = []
        for i, r in enumerate(rows):
            v = r[idx]
            if i == 0 or v != rows[i - 1][idx]:
                out.append((r[0], v))
        return out

    kt = trans(1)
    st = trans(3)
    dt = [x for x in trans(4)]
    print()
    print("kernel tach changes : %d  (every ~%.2f s)"
          % (len(kt), dur / max(1, len(kt))))
    print("state.rpm changes   : %d  (every ~%.2f s)"
          % (len(st), dur / max(1, len(st))))
    print("row text changes    : %d  (every ~%.2f s)"
          % (len(dt), dur / max(1, len(dt))))

    # how long after a kernel change does the row show the matching number?
    lags = []
    for t, raw in kt:
        want = "%.0f RPM" % round(raw / 2.0)
        for t2, txt in dt:
            if t2 >= t and txt == want:
                lags.append(t2 - t)
                break
    if lags:
        lags.sort()
        print("kernel change -> row shows it: min %.2f s, median %.2f s, max %.2f s"
              % (lags[0], lags[len(lags) // 2], lags[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
