#!/usr/bin/env python3
"""Run JS in a Steam GamepadUI CEF target on the Steam Frame devkit.

  python cdp_eval.py --list
  python cdp_eval.py --id <targetId> --expr "document.title"
  python cdp_eval.py --match bar --file probe.js
"""
import argparse
import json
import os
import sys
import urllib.request

import websocket

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# See tools/sf_refresh.py — forward the port or set SF_CDP.
HOST = os.environ.get("SF_CDP", "127.0.0.1:8081")


def targets(host):
    with urllib.request.urlopen(f"http://{host}/json/list", timeout=10) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def evaluate(ws_url, expression, timeout=20.0, await_promise=False):
    ws = websocket.create_connection(ws_url, timeout=timeout)
    ws.settimeout(timeout)
    try:
        ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True,
                       "awaitPromise": await_promise, "userGesture": True},
        }))
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == 1:
                if "error" in r:
                    raise RuntimeError(r["error"])
                res = r["result"]
                if res.get("exceptionDetails"):
                    raise RuntimeError(json.dumps(
                        res["exceptionDetails"], ensure_ascii=False)[:2000])
                return res.get("result", {}).get("value")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--id")
    ap.add_argument("--match")
    ap.add_argument("--expr")
    ap.add_argument("--file")
    ap.add_argument("--await-promise", action="store_true")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--json", action="store_true",
                    help="print raw JSON of the value")
    args = ap.parse_args()

    pages = targets(args.host)
    if args.list:
        for t in pages:
            print(f'{t["id"]}  {t.get("title","")!r}')
            print(f'    {t.get("url","")}')
        return 0

    if args.id:
        sel = [t for t in pages if t["id"] == args.id]
    elif args.match:
        m = args.match.lower()
        sel = [t for t in pages
               if m in (t.get("title", "") + t.get("url", "")).lower()]
    else:
        ap.error("need --list, --id or --match")
    if not sel:
        print("no matching target", file=sys.stderr)
        return 1

    expr = open(args.file, encoding="utf-8").read() if args.file else args.expr
    if not expr:
        ap.error("need --expr or --file")

    for t in sel:
        print(f"### {t.get('title')}  [{t['id']}]", file=sys.stderr)
        try:
            v = evaluate(t["webSocketDebuggerUrl"], expr, args.timeout,
                         args.await_promise)
        except Exception as e:
            print(f"ERR {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if isinstance(v, str):
            print(v)
        else:
            print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
