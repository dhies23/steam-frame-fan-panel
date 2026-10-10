#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the distributable sf-fan-qam release.

    python tools/make_release.py

Builds ``release/sf-fan-qam-<version>/`` from the working tree, then packs it as
both a .tar.gz and a .zip plus a SHA256SUMS file.

The archives are written with Python rather than `tar`/`Compress-Archive` so the
shell scripts keep their executable bit: the Windows filesystem has no such
permission, so the usual tools would silently produce `-rw-rw-rw-` and
`sudo ./install.sh` would fail for whoever unpacks it.
"""
import hashlib
import os
import shutil
import stat
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "sf-fan-qam")
OUT = os.path.join(ROOT, "release")

# (source relative to SRC, destination relative to the release root)
FILES = [
    ("install.sh", "install.sh"),
    ("uninstall.sh", "uninstall.sh"),
    ("diagnose.sh", "diagnose.sh"),
    ("VERSION", "VERSION"),
    ("README.md", "README.md"),
    ("device/sf_fan_qam.js", "device/sf_fan_qam.js"),
    ("device/sf_fan_qamd.py", "device/sf_fan_qamd.py"),
    ("device/sf-fan-qamd.service", "device/sf-fan-qamd.service"),
    ("device/技术说明.md", "docs/TECHNICAL.md"),
]

# extra files that live elsewhere in the repo
EXTRA = [
    (os.path.join(ROOT, "tools", "device", "sfdrive.py"),
     "docs/device-tools/sfdrive.py"),
    (os.path.join(ROOT, "tools", "device", "rpm_latency.py"),
     "docs/device-tools/rpm_latency.py"),
    (os.path.join(ROOT, "tools", "device", "tach_window.py"),
     "docs/device-tools/tach_window.py"),
    (os.path.join(ROOT, "shots", "qam_fan.png"), "preview.png"),
]

EXECUTABLE = {".sh"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def mode_for(dest):
    return 0o755 if os.path.splitext(dest)[1] in EXECUTABLE else 0o644


def build_tree(name):
    dest_root = os.path.join(OUT, name)
    if os.path.isdir(dest_root):
        shutil.rmtree(dest_root)
    os.makedirs(dest_root)

    planned = []
    for rel, dest in FILES:
        planned.append((os.path.join(SRC, rel), dest))
    planned.extend(EXTRA)

    for src, dest in planned:
        if not os.path.isfile(src):
            raise SystemExit("missing source file: %s" % src)
        dst = os.path.join(dest_root, dest.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, mode_for(dest))
        print("  %-34s %o" % (dest, mode_for(dest)))
    return dest_root, planned


def write_targz(name, dest_root):
    path = os.path.join(OUT, name + ".tar.gz")
    with tarfile.open(path, "w:gz") as t:
        for base, dirs, files in os.walk(dest_root):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(base, f)
                rel = os.path.relpath(full, dest_root)
                info = t.gettarinfo(full, arcname=name + "/" + rel.replace(os.sep, "/"))
                # force the mode: Windows reports 0666 for everything
                info.mode = mode_for(rel)
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                with open(full, "rb") as fh:
                    t.addfile(info, fh)
    return path


def write_zip(name, dest_root):
    path = os.path.join(OUT, name + ".zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(dest_root):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(base, f)
                rel = os.path.relpath(full, dest_root).replace(os.sep, "/")
                arc = name + "/" + rel
                info = zipfile.ZipInfo(arc)
                m = mode_for(rel)
                # unix permission bits live in the high half of external_attr
                info.external_attr = (stat.S_IFREG | m) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read())
    return path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    version = open(os.path.join(SRC, "VERSION"), encoding="utf-8").read().strip()
    name = "sf-fan-qam-%s" % version
    print("building %s" % name)

    os.makedirs(OUT, exist_ok=True)
    dest_root, _ = build_tree(name)
    tar = write_targz(name, dest_root)
    zip_ = write_zip(name, dest_root)

    sums = os.path.join(OUT, "SHA256SUMS")
    with open(sums, "w", encoding="ascii", newline="\n") as f:
        for p in (tar, zip_):
            f.write("%s  %s\n" % (sha256(p), os.path.basename(p)))

    print()
    for p in (tar, zip_, sums):
        print("  %-40s %8d bytes" % (os.path.basename(p), os.path.getsize(p)))
    print()
    print("release ready in %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
