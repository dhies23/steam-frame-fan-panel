#!/usr/bin/env python3
"""Syntax-check the injected front-end without running it.

Wraps the script in `new Function(...)`, which parses it in the real CEF
JavaScript engine (the same one Steam GamepadUI uses) but never executes it.

  python tools/sf_syntax_check.py sf-fan-qam/device/sf_fan_qam.js
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf_refresh import CDP, popup  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "sf-fan-qam", "device", "sf_fan_qam.js")
    src = open(path, encoding="utf-8").read()

    p = popup()
    if not p:
        print("barpopup target not found", file=sys.stderr)
        return 1
    c = CDP(p["webSocketDebuggerUrl"])
    try:
        expr = ("(function(){try{new Function(%s);return 'ok';}"
                "catch(e){return 'ERROR: '+e.name+': '+e.message;}})()"
                % json.dumps(src))
        res = c.ev(expr)
    finally:
        c.close()

    print(os.path.basename(path), "->", res)
    return 0 if res == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
