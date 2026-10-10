#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create the GitHub release and upload the packaged artifacts.

    GH_PAT=... python tools/publish_release.py
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = "dhies23/steam-frame-fan-panel"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = os.path.join(ROOT, "release")
VERSION = open(os.path.join(ROOT, "sf-fan-qam", "VERSION"), encoding="utf-8").read().strip()
TAG = "v" + VERSION

BODY = """在 Steam Frame 的快速设置菜单（QAM）底部标签栏「?」右边新增一个风扇标签。

**面板内容**

- 实时转速（RPM）
- 当前占空比（%）
- 六路温度：SoC / CPU / GPU / 内存 / 散热片 / 风扇口
- 手动 PWM 滑杆（20 %–100 %）
- 自动温控开关

**安装**

```bash
tar xzf sf-fan-qam-@V@.tar.gz
cd sf-fan-qam-@V@
sudo ./install.sh
```

**卸载**

```bash
sudo ./uninstall.sh
```

**诊断**（只读，出问题先跑这个）

```bash
sudo ./diagnose.sh > sf-fan.log 2>&1
```

安装脚本会在动手前确认这确实是 Steam Frame，不是就明确拒绝；装完会等最多 15 秒
确认真的注入进了 QAM 页面。卸载脚本删完会验证系统温控确实恢复。

**安全**：手动模式最低 20 %（低于此转速风扇会失速），永不写出 0；SoC ≥ 88 °C、
切回自动、或服务退出时立刻交回系统温控。原生温控服务在手动期间只是被临时停下，
不会被卸载或修改。

GPL-3.0。
""".replace("@V@", VERSION)


def token():
    """A token that can write contents.

    $GH_PAT is asked first, but a fine-grained PAT often has Issues read/write
    while missing Contents write — which pushes just fine (git authenticated
    separately) and yet cannot create a release. So fall back to whatever
    credential git itself uses for github.com.
    """
    env = os.environ.get("GH_PAT")
    if env:
        return env
    p = subprocess.run(["git", "credential", "fill"],
                       input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no token: set GH_PAT or configure a git credential helper")


def api(path, data=None, method=None, raw=None, ctype="application/json", tok=None):
    tok = tok or api.tok
    url = path if path.startswith("http") else "https://api.github.com" + path
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", ctype)
    req.add_header("User-Agent", "sf-fan-qam-publish")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(txt) if txt.strip().startswith(("{", "[")) else txt)
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, txt


api.tok = None


def main():
    api.tok = token()
    files = ["sf-fan-qam-%s.tar.gz" % VERSION, "sf-fan-qam-%s.zip" % VERSION, "SHA256SUMS"]
    for f in files:
        if not os.path.isfile(os.path.join(REL, f)):
            raise SystemExit("missing %s — run tools/make_release.py first" % f)

    code, out = api("/repos/%s/releases" % REPO, data={
        "tag_name": TAG,
        "target_commitish": "main",
        "name": "%s — 首个可分发版本" % TAG,
        "body": BODY,
        "draft": False,
        "prerelease": False,
    })
    print("create release ->", code)
    if code == 422 and isinstance(out, dict):
        # already exists: reuse it
        print("  (already exists, reusing)")
        code, out = api("/repos/%s/releases/tags/%s" % (REPO, TAG))
        if code != 200:
            print(out)
            return 1
    elif code not in (200, 201):
        print(out)
        return 1

    print("  ", out["html_url"])
    upload = out["upload_url"].split("{")[0]
    replace = str(out["id"])

    for f in files:
        path = os.path.join(REL, f)
        with open(path, "rb") as fh:
            blob = fh.read()
        ctype = "application/octet-stream"
        url = "%s?name=%s" % (upload, urllib.parse.quote(f))
        code, res = api(url, raw=blob, method="POST", ctype=ctype)
        if code == 422:
            # a file with that name is already attached — delete and retry
            code2, assets = api("/repos/%s/releases/%s/assets" % (REPO, replace))
            if code2 == 200:
                for a in assets:
                    if a["name"] == f:
                        api("/repos/%s/releases/assets/%s" % (REPO, a["id"]), method="DELETE")
            code, res = api(url, raw=blob, method="POST", ctype=ctype)
        print("  upload %-28s -> %s" % (f, code), (res if code >= 400 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
