#!/usr/bin/env python3
"""Build an offline preview of the injected QAM fan panel.

Takes the live markup captured from the device (shots/panel_dump.json) and
re-assembles it inside the exact ancestor chain Steam GamepadUI uses, with
Valve's own sp.css / library.css (downloaded into shots/css).  Rendering that
in a local browser shows what the panel looks like without a headset.

  python tools/build_preview.py            # writes shots/preview.html
  python tools/build_preview.py --open     # ... and opens it
"""
import argparse
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DUMP = os.path.join(ROOT, "shots", "panel_dump.json")
OUT = os.path.join(ROOT, "shots", "preview.html")

CSS_BASE = "css/"

TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>QAM fan panel preview</title>
<link rel="stylesheet" href="{css}library.css">
<link rel="stylesheet" href="{css}sp.css">
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; background: #10161d; }}
  #popup_target {{
    position: absolute; left: 30px; top: 30px; width: 300px; height: 440px;
    filter: drop-shadow(0 14px 40px rgba(0,0,0,.7));
  }}
  /* sizes the real client applies to the dashboard-bar popup */
  .oVDFbwnRqZKBmE_w0VGuM._3AhmEo885__2csg30k9nno._2F4DqMxa2KcG7EWuFUmyf9,
  ._3DHXr5yONRuNdsrNwBiEm5._-6ESh2T8Qc_pZPgOLBhZJ._2UolfaFpePtd4XWN4777SN {{
    width: 300px; height: 440px;
  }}
</style>
</head>
<body class="{bodycls}">
<div id="popup_target" class="_2Z5vGNEVm8ba7jIvpyR_Oy" style="visibility: visible;">
  <div class="oVDFbwnRqZKBmE_w0VGuM _3AhmEo885__2csg30k9nno _2F4DqMxa2KcG7EWuFUmyf9">
    <div id="VRDashboardBarPopup" data-react-nav-root="VRDashboardBarPopup">
      <div class="BasicUI _3DHXr5yONRuNdsrNwBiEm5 _-6ESh2T8Qc_pZPgOLBhZJ _2UolfaFpePtd4XWN4777SN _3E9A1cvLOkUYdHtJIJ3ioq Panel">
        <div id="QuickAccess-Menu" class="{rootcls}">
          <div class="_3k5MHjpKaOv6C29MKPgd6x"></div>
          <div class="_1gJzx0OgstpPqW34DFUKC6">
            <div class="_3Ag1wVkrYOaZyOUNWGLf3Y Panel">
              <div class="{tabbarcls}">
{tabbar}
              </div>
            </div>
            <div class="_2BB6uf--jFaAmdnwLOqMU7 Panel">
              <div class="_2yKG4XpAWPZeSinfRyiqk1 _3rR0ow-ED56Pvt857Zlf7R">
                <div class="_32AONYfEkmb0E6cwY31wPP oIVg-eNHeYCNPq0blN3Dk"
                     style="position: static; display: flex;">
{panel}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""


def indent(html, spaces):
    pad = " " * spaces
    return "\n".join(pad + line for line in html.splitlines())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DUMP)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--css", default=CSS_BASE)
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--zoom", type=float, default=1.0,
                    help="CSS zoom applied to the popup (for close-up renders)")
    ap.add_argument("--scroll", type=int, default=0,
                    help="scroll the panel body down by this many px")
    args = ap.parse_args()

    with open(args.dump, encoding="utf-8-sig") as f:
        d = json.load(f)

    panel = d.get("panelHTML")
    tabbar = d.get("tabbarHTML")
    if not panel or not tabbar:
        print("dump is missing panelHTML/tabbarHTML; run tools/sf_refresh.py first",
              file=sys.stderr)
        return 1

    html = TEMPLATE.format(
        css=args.css,
        bodycls=d.get("bodyCls") or "GamepadMode BasicUI",
        rootcls=d.get("rootCls") or "Panel",
        tabbarcls="Panel",
        tabbar=indent(tabbar, 16),
        panel=indent(panel, 18),
    )
    if args.zoom and args.zoom != 1.0:
        html = html.replace(
            "#popup_target {",
            "#popup_target {\n    zoom: %s;" % args.zoom)
    if args.scroll:
        html = html.replace(
            "</body>",
            "<script>window.addEventListener('load',function(){"
            "var b=document.getElementById('sf_fan_body');"
            "if(b){b.scrollTop=%d;}});</script>\n</body>" % args.scroll)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", args.out)

    if args.open:
        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(chrome):
            subprocess.Popen([chrome, "--new-window", args.out])
        else:
            os.startfile(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
