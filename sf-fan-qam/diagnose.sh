#!/usr/bin/env bash
# Steam Frame QAM 风扇面板 —— 一键诊断
#
#   sudo ./diagnose.sh              # 打印到屏幕
#   sudo ./diagnose.sh > sf-fan.log # 存成文件发给作者
#
# 只读，不改任何东西。把所有可能出问题的环节都查一遍并给出结论。
set -uo pipefail

SERVICE="sf-fan-qamd.service"
STOCK="deckard-fan-control.service"
DEST="/home/steamos/sf-fan-qam"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m── %s\033[0m\n' "$*"; }

echo "sf-fan-qam 诊断报告"
echo "生成时间：$(date -Is)"
echo "主机名　：$(hostname)"

# --------------------------------------------------------------------------
step "系统"
# --------------------------------------------------------------------------
. /etc/os-release 2>/dev/null && echo "  系统　　：$PRETTY_NAME"
echo "  内核　　：$(uname -r)"
echo "  架构　　：$(uname -m)"
echo "  运行时间：$(uptime -p 2>/dev/null || uptime)"
if [ "$(id -u)" -eq 0 ]; then ok "以 root 运行"; else
  warn "不是 root —— 部分检查会失败，建议 sudo ./diagnose.sh"; fi

# --------------------------------------------------------------------------
step "风扇硬件"
# --------------------------------------------------------------------------
FAN_DIR=""
for h in /sys/class/hwmon/hwmon*; do
  if [ "$(cat "$h/name" 2>/dev/null)" = "slg4ax46073v" ]; then
    FAN_DIR="$h"; break
  fi
done

if [ -z "$FAN_DIR" ]; then
  bad "找不到 hwmon「slg4ax46073v」—— 这不是 Steam Frame，或者风扇驱动没起来"
  echo "  现有 hwmon："
  for h in /sys/class/hwmon/hwmon*; do
    [ -f "$h/name" ] && echo "    - $(cat "$h/name")"
  done
else
  ok "hwmon 路径：$FAN_DIR"
  PWM="$(cat "$FAN_DIR/pwm1" 2>/dev/null || echo '?')"
  RAW="$(cat "$FAN_DIR/fan1_input" 2>/dev/null || echo 0)"
  echo "  pwm1　　　　：$PWM %"
  echo "  pwm1_enable ：$(cat "$FAN_DIR/pwm1_enable" 2>/dev/null || echo '?')"
  echo "  转速　　　　：$(( RAW / 2 )) RPM（原始 $RAW）"
  echo "  报警位　　　：$(cat "$FAN_DIR/fan1_alarm" 2>/dev/null || echo '?')"
  if [ "$PWM" != "?" ] && [ "$PWM" -gt 0 ] 2>/dev/null; then
    ok "风扇在转，占空比非零"
  else
    bad "pwm1 为 0 —— 风扇可能被停住了，请立即执行：sudo systemctl start $STOCK"
  fi
fi

# --------------------------------------------------------------------------
step "系统温控（原生）"
# --------------------------------------------------------------------------
if systemctl list-unit-files "$STOCK" >/dev/null 2>&1; then
  ST="$(systemctl is-active "$STOCK" 2>/dev/null)"
  if [ "$ST" = "active" ]; then ok "$STOCK 运行中"
  else warn "$STOCK 状态：$ST（手动模式下这是正常的）"; fi
  echo "  重启次数：$(systemctl show "$STOCK" -p NRestarts --value 2>/dev/null)"
  echo "  启动时间：$(systemctl show "$STOCK" -p ExecMainStartTimestamp --value 2>/dev/null)"
else
  warn "没找到 $STOCK"
fi

# --------------------------------------------------------------------------
step "面板服务"
# --------------------------------------------------------------------------
if systemctl list-unit-files "$SERVICE" >/dev/null 2>&1; then
  echo "  已启用　：$(systemctl is-enabled "$SERVICE" 2>/dev/null)"
  echo "  状态　　：$(systemctl is-active "$SERVICE" 2>/dev/null)"
  echo "  重启次数：$(systemctl show "$SERVICE" -p NRestarts --value 2>/dev/null)"
  echo "  内存　　：$(systemctl show "$SERVICE" -p MemoryCurrent --value 2>/dev/null) 字节"
  echo "  累计 CPU：$(systemctl show "$SERVICE" -p CPUUsageNSec --value 2>/dev/null) ns"
  if systemctl is-active --quiet "$SERVICE"; then
    ok "服务在跑"
    # 只有在 JS 内容变了的时候才重新注入，所以这里看的是「最后一次注入」
    LAST_INJECT="$(journalctl -u "$SERVICE" -o short-iso --no-pager 2>/dev/null \
                   | grep 'inject ->' | tail -1)"
    if [ -n "$LAST_INJECT" ]; then
      ok "最后一次注入：$(echo "$LAST_INJECT" | sed 's/.*\[sf-fan-qamd\] //')"
      echo "  注入时间：$(echo "$LAST_INJECT" | awk '{print $1}')"
    else
      warn "日志里没有注入记录（服务刚装好？或者 SteamVR 一直没起来）"
    fi
    ERRS="$(journalctl -u "$SERVICE" -o cat --since "-10 min" 2>/dev/null \
            | grep -c 'failed' || true)"
    if [ "${ERRS:-0}" -gt 0 ]; then
      bad "最近 10 分钟有 $ERRS 条失败日志："
      journalctl -u "$SERVICE" -o cat --since "-10 min" 2>/dev/null \
        | grep 'failed' | tail -5 | sed 's/^/    /'
    else
      ok "最近 10 分钟没有失败日志"
    fi
  else
    bad "服务没在运行"
  fi
else
  bad "$SERVICE 未安装"
fi

# --------------------------------------------------------------------------
step "SteamVR / GamepadUI"
# --------------------------------------------------------------------------
if pgrep -f steamwebhelper >/dev/null 2>&1; then
  ok "steamwebhelper 在运行"
  echo "  进程数：$(pgrep -fc steamwebhelper)"
else
  warn "steamwebhelper 没在运行 —— 界面相关的一切都要等它起来"
fi

if pgrep -f "gamescope" >/dev/null 2>&1; then
  ok "gamescope 在运行"
  if ps -eo args 2>/dev/null | grep -q "backend openvr"; then
    ok "VR 后端已启用（--backend openvr）"
  else
    warn "没看到 --backend openvr：这台机器现在可能不在 VR 模式"
    warn "  QAM 里的风扇标签只有在 GamepadUI 起来之后才会出现"
  fi
else
  warn "gamescope 没在运行"
fi

# --------------------------------------------------------------------------
step "CEF 调试端口（注入靠它）"
# --------------------------------------------------------------------------
if curl -s --max-time 3 http://127.0.0.1:8080/json/version >/dev/null 2>&1; then
  ok "127.0.0.1:8080 可访问"
  echo "  $(curl -s --max-time 3 http://127.0.0.1:8080/json/version \
        | tr -d '\n' | cut -c1-160)"
  echo "  QAM 页面 target："
  if command -v python3 >/dev/null; then
    curl -s --max-time 3 http://127.0.0.1:8080/json/list | python3 -c '
import json,sys
try: ts=json.load(sys.stdin)
except Exception: ts=[]
hit=[t for t in ts if "barpopup" in (t.get("title","")+t.get("url",""))]
for t in ts:
    mark = "  <== QAM" if t in hit else ""
    print("    - %-44s %s%s" % ((t.get("title") or "")[:44], t.get("type"), mark))
if not hit:
    print("    （没有 barpopup target：QAM 可能还没被打开过）")
'
  fi
else
  warn "127.0.0.1:8080 连不上 —— SteamVR 没启动，或者调试端口被关了"
fi

# --------------------------------------------------------------------------
step "文件"
# --------------------------------------------------------------------------
for f in sf_fan_qam.js sf_fan_qamd.py sf-fan-qamd.service README.md; do
  if [ -f "$DEST/$f" ]; then
    ok "$DEST/$f  ($(stat -c '%s 字节, %U, %a' "$DEST/$f"))"
  else
    warn "$DEST/$f 不存在"
  fi
done
[ -f /etc/systemd/system/sf-fan-qamd.service ] \
  && ok "/etc/systemd/system/sf-fan-qamd.service" \
  || warn "/etc/systemd/system/sf-fan-qamd.service 不存在"

# --------------------------------------------------------------------------
step "最近日志"
# --------------------------------------------------------------------------
journalctl -u "$SERVICE" -n 20 --no-pager -o short-iso 2>/dev/null \
  | sed 's/^/  /' || echo "  （没有日志）"
# --------------------------------------------------------------------------
step "内核里的风扇消息"
# --------------------------------------------------------------------------
dmesg 2>/dev/null | grep -i "slg4ax\|tach\|fan" | tail -10 | sed 's/^/  /' \
  || echo "  （读不到 dmesg，试试 sudo）"

# --------------------------------------------------------------------------
step "结论"
# --------------------------------------------------------------------------
PROBLEMS=0
if [ -z "$FAN_DIR" ]; then bad "风扇硬件没找到"; PROBLEMS=$((PROBLEMS+1)); fi
if ! systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  bad "面板服务没在跑 —— 先看上面的日志"; PROBLEMS=$((PROBLEMS+1)); fi
if ! pgrep -f steamwebhelper >/dev/null 2>&1; then
  warn "SteamVR 没开，界面相关的问题现在无法判断"; fi
if [ "$PROBLEMS" -eq 0 ]; then
  ok "没有发现硬性故障。如果头显里仍然看不到风扇标签，请把这份输出发给作者"
fi

cat <<'EOF'

────────────────────────────────────────────────────────────
 把以上全部内容复制发给作者即可。
 想存成文件：  sudo ./diagnose.sh > sf-fan.log 2>&1
────────────────────────────────────────────────────────────
EOF
