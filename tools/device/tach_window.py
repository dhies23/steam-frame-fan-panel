"""Is the tach a 60-second rolling average?

At ~3500 RPM the fan turns 58.5 times a second, two tach pulses per turn, so a
pulse *count* over 60 s is ~7026 -- exactly the number in fan1_input, and exactly
2x the RPM.  If that is what the chip reports, then after a step change the
reading must ramp towards the new speed over about a minute instead of jumping,
and the size of each 3-second step must be tiny.

    python3 /tmp/tach_window.py
"""
import os
import sys
import time

sys.path.insert(0, "/home/steamos/sf-fan-qam")
sys.path.insert(0, "/tmp")
import sfdrive  # noqa: E402


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


def main():
    d = fan_dir()
    tach = os.path.join(d, "fan1_input")
    pwm = os.path.join(d, "pwm1")

    c = sfdrive.ensure_panel()
    if c is None:
        print("could not get the panel on screen")
        return 1
    try:
        print(">>> manual 25 %, settle")
        sfdrive.drag_slider(c, 25)
        time.sleep(45)
        print("    pwm1=%s raw=%s" % (open(pwm).read().strip(),
                                      open(tach).read().strip()))

        print(">>> step to 100 %% and watch for 150 s")
        sfdrive.drag_slider(c, 100)
        t0 = time.time()
        prev = None
        while time.time() - t0 < 150:
            raw = int(open(tach).read())
            if raw != prev:
                print("    +%6.1fs  pwm1=%-4s raw=%-7d rpm=%-8.1f"
                      % (time.time() - t0, open(pwm).read().strip(), raw, raw / 2.0))
                prev = raw
            time.sleep(0.4)
    finally:
        c.evaluate("window.__SF_FAN__.setAuto()")
        c.close()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
