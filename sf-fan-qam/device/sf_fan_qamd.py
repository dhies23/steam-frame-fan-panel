#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sf-fan-qamd - Steam Frame QAM fan / temperature panel backend.

Injects ``sf_fan_qam.js`` into the Steam GamepadUI quick-access-menu popup
(CEF target ``valve.steam.gamepadui.barpopup``, devtools endpoint on
127.0.0.1:8080) and keeps it fed with live fan RPM, PWM duty and board
temperatures.  Fan-speed requests coming back from the UI are applied to
/sys/class/hwmon/<slg4ax46073v>/pwm1.

Needs root: writing pwm1 and stopping/starting deckard-fan-control.service.

The device has no python websocket library, so a minimal RFC6455 client is
implemented on top of the stdlib socket module.

Usage:
    sf_fan_qamd.py --js /path/to/sf_fan_qam.js        # run the daemon
    sf_fan_qamd.py --status                           # print one JSON snapshot
    sf_fan_qamd.py --set-pwm 55                       # manual pwm
    sf_fan_qamd.py --auto                             # hand back to the EC
"""

from __future__ import annotations

import argparse
import base64
import glob
import hashlib
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

CDP_HTTP = "http://127.0.0.1:8080"
TARGET_MATCH = "valve.steam.gamepadui.barpopup"
BINDING_NAME = "__sfFanSend"

FAN_HWMON_NAME = "slg4ax46073v"
FAN_SERVICE = "deckard-fan-control.service"

IIO = "/sys/bus/iio/devices/iio:device0"

POLL_INTERVAL = 0.4          # seconds between UI pushes
SAFETY_TEMP_C = 88.0         # force auto control above this while manual
# The delta fan stalls below ~20 % duty and the stock controller never goes
# under 30 %. Anything the UI sends is clamped into this window, so a slider
# that is briefly collapsed or hidden can never be read as "stop the fan".
MANUAL_MIN_PWM = 20
MANUAL_MAX_PWM = 100

HW = "/sys/class/hwmon"

CPU_SENSORS = ["cpu%d_thermal" % i for i in range(8)] + \
              ["cpuss%d_thermal" % i for i in range(4)]
GPU_SENSORS = ["gpuss_%d_thermal" % i for i in range(5)]
SOC_EXTRA = ["aoss0_thermal", "aoss1_thermal", "aoss2_thermal",
             "video_thermal", "nsphvx0_thermal", "nsphvx1_thermal",
             "nsphmx0_thermal", "nsphmx1_thermal", "nsphmx2_thermal",
             "nsphmx3_thermal", "modem3_thermal"]

TEMP_KEYS = ["soc", "cpu", "gpu", "ddr", "heatsink", "fan"]


def log(*a):
    print("[sf-fan-qamd]", *a, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# minimal websocket client (stdlib only)
# --------------------------------------------------------------------------

class WSError(Exception):
    pass


class WebSocket:
    def __init__(self, url, timeout=10.0):
        m = re.match(r"ws://([^/:]+)(?::(\d+))?(/.*)?$", url)
        if not m:
            raise WSError("bad ws url: %r" % url)
        host = m.group(1)
        port = int(m.group(2) or 80)
        path = m.group(3) or "/"

        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\n"
               "Host: %s:%d\r\n"
               "Upgrade: websocket\r\n"
               "Connection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key))
        self.sock.sendall(req.encode())

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSError("handshake: connection closed")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        status = head.split(b"\r\n")[0]
        if b"101" not in status:
            raise WSError("handshake failed: %s" % status.decode("utf-8", "replace"))
        self._buf = rest
        self._frag = b""

    # -- low level ---------------------------------------------------------
    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, payload, opcode=0x1):
        header = bytearray()
        header.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack("!H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def send_text(self, text):
        self._send_frame(text.encode("utf-8"), 0x1)

    def recv_text(self):
        while True:
            b1, b2 = self._read(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if masked else b""
            payload = self._read(length)
            if mask:
                payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))

            if opcode == 0x8:
                raise WSError("server sent close")
            if opcode == 0x9:
                self._send_frame(payload, 0xA)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x0, 0x1, 0x2):
                self._frag += payload
                if fin:
                    data, self._frag = self._frag, b""
                    return data.decode("utf-8", "replace")
            else:
                continue

    def close(self):
        try:
            self._send_frame(b"", 0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# CDP
# --------------------------------------------------------------------------

class CDP:
    def __init__(self, ws_url):
        self.ws = WebSocket(ws_url)
        self._id = 0
        self.events = []

    def call(self, method, params=None, timeout=10.0):
        self._id += 1
        mid = self._id
        self.ws.send_text(json.dumps(
            {"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                raise WSError("timeout waiting for %s" % method)
            msg = json.loads(self.ws.recv_text())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise WSError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def evaluate(self, expr, timeout=10.0):
        res = self.call("Runtime.evaluate",
                        {"expression": expr, "returnByValue": True,
                         "userGesture": True, "awaitPromise": False},
                        timeout=timeout)
        if res.get("exceptionDetails"):
            raise WSError("js exception: %s" % json.dumps(
                res["exceptionDetails"], ensure_ascii=False)[:400])
        return res.get("result", {}).get("value")

    def drain_events(self):
        out, self.events = self.events, []
        return out

    def close(self):
        self.ws.close()


def http_json(url, timeout=5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def find_target():
    """Return the devtools websocket url of the QAM popup, or None."""
    try:
        targets = http_json(CDP_HTTP + "/json/list")
    except Exception:
        return None
    for t in targets:
        blob = (t.get("title") or "") + (t.get("url") or "")
        if TARGET_MATCH in blob and t.get("type") == "page":
            return t.get("webSocketDebuggerUrl")
    return None


# --------------------------------------------------------------------------
# sensors
# --------------------------------------------------------------------------

class Sensors:
    def __init__(self):
        self._hw = {}
        self._scanned = 0.0
        self._temps = None
        self._temps_at = 0.0

    def scan(self, force=False):
        if not force and time.time() - self._scanned < 30:
            return self._hw
        hw = {}
        for d in glob.glob(HW + "/hwmon*"):
            try:
                with open(os.path.join(d, "name")) as f:
                    hw[f.read().strip()] = d
            except Exception:
                continue
        self._hw = hw
        self._scanned = time.time()
        return hw

    def _read(self, path):
        try:
            with open(path) as f:
                return int(f.read().strip())
        except Exception:
            return None

    def hwmon_temp(self, name):
        d = self.scan().get(name)
        if not d:
            return None
        v = self._read(os.path.join(d, "temp1_input"))
        return None if v is None else v / 1000.0

    def iio_temp(self, node):
        v = self._read(os.path.join(IIO, node))
        return None if v is None else v / 1000.0

    def fan_path(self):
        d = self.scan().get(FAN_HWMON_NAME)
        return d

    def read_fan(self):
        d = self.fan_path()
        if not d:
            return None, None
        raw = self._read(os.path.join(d, "fan1_input"))
        pwm = self._read(os.path.join(d, "pwm1"))
        rpm = None if raw is None else raw / 2.0     # delta fan: 2 periods / rev
        return rpm, pwm

    def read_temps(self, max_age=1.0):
        """Temperatures move far slower than RPM, and each reading opens ~48
        sysfs files, so cache them briefly: the fan tach can then be polled
        several times a second without burning CPU on thermistors."""
        now = time.time()
        if self._temps is not None and now - self._temps_at < max_age:
            return self._temps

        def mx(names):
            vals = [self.hwmon_temp(n) for n in names]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else None

        cpu = mx(CPU_SENSORS)
        gpu = mx(GPU_SENSORS)
        soc = mx(CPU_SENSORS + GPU_SENSORS + SOC_EXTRA)
        self._temps = {
            "soc": soc,
            "cpu": cpu,
            "gpu": gpu,
            "ddr": self.hwmon_temp("ddr_thermal"),
            "heatsink": self.iio_temp("in_temp_pcba_at_heat_sink_fins_input"),
            "fan": self.iio_temp("in_temp_pcba_at_fan_exhaust_input"),
        }
        self._temps_at = now
        return self._temps


# --------------------------------------------------------------------------
# fan control
# --------------------------------------------------------------------------

def systemctl(*args):
    return subprocess.run(["systemctl"] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True)


class FanControl:
    def __init__(self, sensors: Sensors):
        self.sensors = sensors
        self.mode = "auto"
        self.last_pwm = None
        self.error = None
        self.written_at = 0.0
        self._checked_at = 0.0

    # -- helpers -----------------------------------------------------------
    def _write_pwm(self, pwm):
        d = self.sensors.fan_path()
        if not d:
            raise RuntimeError("fan hwmon not found")
        pwm = max(MANUAL_MIN_PWM, min(MANUAL_MAX_PWM, int(round(pwm))))
        # pwm1 is ignored while the chip runs its own curve (pwm1_enable=2)
        try:
            with open(os.path.join(d, "pwm1_enable"), "w") as f:
                f.write("1")
        except Exception:
            pass
        with open(os.path.join(d, "pwm1"), "w") as f:
            f.write(str(pwm))
        self.last_pwm = pwm
        self.written_at = time.time()
        return pwm

    def _service_active(self):
        r = systemctl("is-active", FAN_SERVICE)
        return r.stdout.strip() == "active"

    def _stop_service(self):
        """Stop the stock controller and make sure it really stayed down.

        The old code fired one `systemctl stop` and moved on; if that call lost
        a race the controller kept its own PWM and manual control silently
        stopped working after a moment."""
        for attempt in range(4):
            systemctl("stop", FAN_SERVICE)
            time.sleep(0.35)
            if not self._service_active():
                log("stopped %s" % FAN_SERVICE)
                return True
            log("stop attempt %d: %s still active, retrying"
                % (attempt + 1, FAN_SERVICE))
        log("WARNING: could not stop %s" % FAN_SERVICE)
        return False

    def _start_service(self):
        for attempt in range(4):
            systemctl("start", FAN_SERVICE)
            time.sleep(0.35)
            if self._service_active():
                log("started %s" % FAN_SERVICE)
                return True
            log("start attempt %d: %s not active yet, retrying"
                % (attempt + 1, FAN_SERVICE))
        log("WARNING: could not start %s" % FAN_SERVICE)
        return False

    # -- public ------------------------------------------------------------
    def set_manual(self, pwm=None):
        if self.mode != "manual":
            # Hold whatever the automatic controller was asking for, so
            # switching to manual does not itself change the fan speed. Read it
            # *before* stopping: once the controller is gone the EC may leave
            # pwm1 at 0.
            if pwm is None:
                pwm = self.sensors.read_fan()[1]
            self._stop_service()
            self.mode = "manual"
        if pwm is None:
            pwm = self.last_pwm
        if pwm is None:
            pwm = MANUAL_MIN_PWM
        pwm = self._write_pwm(pwm)
        self.error = None
        return pwm

    def set_auto(self):
        if self.mode != "auto":
            self.mode = "auto"
            self.last_pwm = None
            self._start_service()
        self.error = None

    def safety_check(self, temps):
        if self.mode != "manual":
            return
        hot = temps.get("soc")
        if hot is not None and hot >= SAFETY_TEMP_C:
            log("safety: SoC %.1fC >= %.0fC, restoring auto fan control"
                % (hot, SAFETY_TEMP_C))
            self.set_auto()
            self.error = "温度过高，已自动恢复系统温控"

    def watchdog(self):
        """Keep manual control honest while it is selected.

        Two things can quietly end it: the stock controller coming back (its
        unit is only stopped, so anything that pulls it in again wins), and the
        EC resetting pwm1. Both used to look like "the slider stopped working
        after a moment"."""
        if self.mode != "manual" or self.last_pwm is None:
            return
        now = time.time()
        if now - getattr(self, "_checked_at", 0) >= 3.0:
            self._checked_at = now
            if self._service_active():
                log("watchdog: %s is back, stopping it again" % FAN_SERVICE)
                self._stop_service()
        _rpm, pwm = self.sensors.read_fan()
        if pwm is None or abs(pwm - self.last_pwm) > 2:
            log("watchdog: pwm1 drifted (%s, wanted %s) - re-asserting"
                % (pwm, self.last_pwm))
            try:
                self._write_pwm(self.last_pwm)
            except Exception as e:
                log("watchdog write failed: %s" % e)


# --------------------------------------------------------------------------
# daemon
# --------------------------------------------------------------------------

class Daemon:
    def __init__(self, js_path):
        self.js_path = js_path
        self.js = open(js_path, encoding="utf-8").read()
        # Content hash: any edit to the JS forces a fresh injection into an
        # already-instrumented page.
        self.build = hashlib.sha1(self.js.encode("utf-8")).hexdigest()[:12]
        self.code = self.js + (
            '\n;try{window.__SF_FAN__.build="%s";}catch(e){}\n' % self.build)
        self.sensors = Sensors()
        self.fan = FanControl(self.sensors)
        self.cdp = None
        self.ws_url = None
        self.running = True

    # -- injection ---------------------------------------------------------
    def connect(self):
        url = find_target()
        if not url:
            return False
        if self.cdp and url == self.ws_url:
            return True
        if self.cdp:
            try:
                self.cdp.close()
            except Exception:
                pass
            self.cdp = None
        try:
            self.cdp = CDP(url)
            self.cdp.call("Runtime.enable")
            self.cdp.call("Runtime.addBinding", {"name": BINDING_NAME})
            self.ws_url = url
            log("attached to %s" % url)
            return True
        except Exception as e:
            log("attach failed: %s" % e)
            self.cdp = None
            return False

    def inject(self):
        # The script installs a MutationObserver that builds the tab as soon
        # as the QAM DOM exists, so the build marker alone tells us whether a
        # fresh injection is needed (a page reload clears it).
        probe = ("(window.__SF_FAN__ && window.__SF_FAN__.build) || ''")
        try:
            present = self.cdp.evaluate(probe)
        except Exception as e:
            log("probe failed: %s" % e)
            self.cdp = None
            return
        if present == self.build:
            return
        try:
            res = self.cdp.evaluate(self.code, timeout=20)
            log("inject -> %s (build %s)" % (res, self.build))
        except Exception as e:
            log("inject failed: %s" % e)

    # -- state -------------------------------------------------------------
    def snapshot(self):
        rpm, pwm = self.sensors.read_fan()
        temps = self.sensors.read_temps()
        self.fan.safety_check(temps)
        self.fan.watchdog()
        if self.fan.mode == "manual":
            # While we own the fan the slider must keep showing what the user
            # asked for: the raw register can lag or read 0 for a moment right
            # after a write, and echoing that made the control snap back.
            shown = self.fan.last_pwm if self.fan.last_pwm is not None else pwm
        else:
            # while the stock controller owns the fan, report what it set
            shown = pwm if pwm is not None else self.fan.last_pwm
        return {
            "rpm": rpm,
            "pwm": shown,
            "hwPwm": pwm,
            "mode": self.fan.mode,
            "maxTemp": temps.get("soc"),
            "temps": [{"key": k, "c": temps.get(k)} for k in TEMP_KEYS],
            "error": self.fan.error,
            "manualMin": MANUAL_MIN_PWM,
        }

    def push(self):
        st = self.snapshot()
        try:
            self.cdp.evaluate(
                "window.__SF_FAN__ && window.__SF_FAN__.setState(%s)"
                % json.dumps(st), timeout=8)
        except Exception as e:
            log("push failed: %s" % e)
            self.cdp = None
            return
        self.handle_commands()

    def handle_commands(self):
        for ev in self.cdp.drain_events():
            if ev.get("method") != "Runtime.bindingCalled":
                continue
            params = ev.get("params") or {}
            if params.get("name") != BINDING_NAME:
                continue
            raw = params.get("payload") or ""
            try:
                msg = json.loads(raw)
            except Exception:
                log("bad command payload: %r" % raw[:200])
                continue
            self.execute(msg)

    def execute(self, msg):
        cmd = msg.get("cmd")
        val = msg.get("value")
        log("command: %s %s" % (cmd, val))
        try:
            if cmd == "set_manual":
                self.fan.set_manual()
            elif cmd == "set_auto":
                self.fan.set_auto()
            elif cmd in ("set_pwm", "preview_pwm"):
                if val is None:
                    return
                self.fan.set_manual(int(val))
        except Exception as e:
            log("command failed: %s" % e)
            self.fan.error = str(e)

    # -- loop --------------------------------------------------------------
    def run(self):
        log("started; js=%s" % self.js_path)
        while self.running:
            try:
                if not self.connect():
                    time.sleep(1.0)
                    continue
                self.inject()
                self.push()
            except Exception as e:
                log("loop error: %s" % e)
                self.cdp = None
            time.sleep(POLL_INTERVAL)

    def stop(self, *_a):
        self.running = False

    def cleanup(self):
        log("shutting down; restoring automatic fan control")
        try:
            self.fan.set_auto()
        except Exception as e:
            log("restore failed: %s" % e)
        # remove the tab/panel so no dead UI is left behind
        try:
            if self.cdp:
                self.cdp.evaluate(
                    "window.__SF_FAN__ && window.__SF_FAN__.teardown()",
                    timeout=5)
                log("removed injected UI")
        except Exception as e:
            log("teardown failed: %s" % e)
        if self.cdp:
            try:
                self.cdp.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main():
    global POLL_INTERVAL

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--js", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "sf_fan_qam.js"))
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--set-pwm", type=int)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--interval", type=float, default=POLL_INTERVAL)
    args = ap.parse_args()

    POLL_INTERVAL = args.interval

    if args.status or args.set_pwm is not None or args.auto:
        s = Sensors()
        f = FanControl(s)
        if args.auto:
            f.set_auto()
        if args.set_pwm is not None:
            f.set_manual(args.set_pwm)
        rpm, pwm = s.read_fan()
        print(json.dumps({
            "rpm": rpm, "pwm": pwm, "mode": f.mode,
            "temps": s.read_temps(),
        }, ensure_ascii=False, indent=2))
        return 0

    d = Daemon(args.js)
    signal.signal(signal.SIGTERM, d.stop)
    signal.signal(signal.SIGINT, d.stop)
    try:
        d.run()
    finally:
        d.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
