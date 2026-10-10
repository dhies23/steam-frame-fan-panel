#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set the repo description and topics using whatever token git already uses."""
import json
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "dhies23/steam-frame-fan-panel"
DESC = "Steam Frame（SteamOS + SteamVR GamepadUI）快速设置菜单里的风扇面板：实时温度、实时 RPM、手动/自动温控切换。一键安装 + 一键卸载。"
TOPICS = ["steam-frame", "steamvr", "steamos", "deckard", "fan-control", "gamepadui", "qam", "python"]


def token():
    p = subprocess.run(["git", "credential", "fill"],
                       input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no token")


def call(tok, method, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request("https://api.github.com" + path, data=body, method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "publish")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


tok = token()
print("description ->", call(tok, "PATCH", "/repos/" + REPO, {"description": DESC})[0])
code, txt = call(tok, "PUT", "/repos/%s/topics" % REPO, {"names": TOPICS})
print("topics      ->", code)
if code >= 400:
    print("   ", txt[:200])
