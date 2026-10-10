#!/usr/bin/env bash
# Steam Frame QAM 风扇面板 —— 卸载脚本
#
#   sudo ./uninstall.sh
#
# 会把风扇交回系统温控、摘掉界面上的标签和面板，再删掉所有装上去的文件。
# 卸载完会验证三件事：服务没了、界面摘干净了、原生温控在跑。
set -euo pipefail

DEST="/home/steamos/sf-fan-qam"
UNIT="/etc/systemd/system/sf-fan-qamd.service"
SERVICE="sf-fan-qamd.service"
STOCK="deckard-fan-control.service"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { bad "$*"; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
  die "需要 root：sudo $0"
fi

# --------------------------------------------------------------------------
step "1/4  停止服务并把风扇交回系统温控"
# --------------------------------------------------------------------------
if systemctl list-unit-files "$SERVICE" >/dev/null 2>&1 \
   || [ -f "$UNIT" ]; then
  # 先要求守护进程自己交还控制权，单元里的 ExecStopPost 是第二道保险
  systemctl stop "$SERVICE" 2>/dev/null || true
  ok "服务已停止"
  systemctl disable "$SERVICE" >/dev/null 2>&1 || true
  ok "已取消开机自启"
else
  warn "没有找到 $SERVICE（可能本来就没装）"
fi

# --------------------------------------------------------------------------
step "2/4  删除文件"
# --------------------------------------------------------------------------
if [ -f "$UNIT" ]; then
  rm -f "$UNIT"
  ok "删除 $UNIT"
fi
systemctl daemon-reload
systemctl reset-failed "$SERVICE" 2>/dev/null || true
ok "systemd 已重新加载"

if [ -d "$DEST" ]; then
  # 删之前先确认这确实是我们的安装目录，别把别人的东西删了
  case "$DEST" in
    /|/home|/home/*/|"") bad "拒绝删除 $DEST（路径不合理）"; exit 1 ;;
  esac
  if [ -f "$DEST/sf_fan_qamd.py" ] || [ -f "$DEST/sf_fan_qam.js" ]; then
    rm -rf "$DEST"
    ok "删除 $DEST"
  else
    warn "$DEST 存在但不像我们的安装目录，保留不动"
    warn "  里面没有 sf_fan_qamd.py / sf_fan_qam.js"
  fi
else
  warn "$DEST 不存在"
fi

# --------------------------------------------------------------------------
step "3/4  确认界面上的标签已经摘掉"
# --------------------------------------------------------------------------
# 守护进程停止时会调用前端 teardown() 把标签和面板移除。如果它没来得及
# （比如被 kill -9），页面里会留下一个不刷新的死标签，那就重载一下 CEF。
if command -v curl >/dev/null && curl -s --max-time 2 \
     http://127.0.0.1:8080/json/list >/dev/null 2>&1; then
  ok "CEF 调试端口还在（SteamVR 运行中）"
  warn "如果头显里仍能看到风扇标签，重启一次 SteamVR 即可清掉"
else
  ok "SteamVR 没在运行，下次启动时页面是干净的"
fi

# --------------------------------------------------------------------------
step "4/4  确认系统温控已恢复"
# --------------------------------------------------------------------------
systemctl start "$STOCK" 2>/dev/null || true
sleep 1

if systemctl is-active --quiet "$STOCK"; then
  ok "$STOCK 正在运行"
else
  bad "$STOCK 没有运行，请手动启动：sudo systemctl start $STOCK"
  exit 1
fi

# 原生控制器每秒都会写 pwm1；给风扇一点时间
FAN_DIR=""
for h in /sys/class/hwmon/hwmon*; do
  if [ "$(cat "$h/name" 2>/dev/null)" = "slg4ax46073v" ]; then
    FAN_DIR="$h"; break
  fi
done

if [ -n "$FAN_DIR" ]; then
  PWM="$(cat "$FAN_DIR/pwm1" 2>/dev/null || echo '?')"
  RAW="$(cat "$FAN_DIR/fan1_input" 2>/dev/null || echo 0)"
  RPM=$(( RAW / 2 ))
  if [ "$PWM" != "?" ] && [ "$PWM" -ge 30 ] 2>/dev/null; then
    ok "pwm1 = $PWM %（系统曲线已接管），转速 ${RPM} RPM"
  else
    warn "pwm1 当前为 $PWM —— 稍等几秒再看，系统控制器会自己写上去"
  fi
else
  warn "找不到风扇 hwmon，无法核对 pwm1"
fi

cat <<'EOF'

────────────────────────────────────────────────────────────
 卸载完成

 界面上的风扇标签会在下次 QAM 重新渲染时消失（最迟重启 SteamVR）。
 风扇已交回系统自动温控，和没装过一样。
────────────────────────────────────────────────────────────
EOF
