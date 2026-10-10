#!/usr/bin/env bash
# Steam Frame QAM 风扇面板 —— 安装脚本
#
#   sudo ./install.sh
#
# 做四件事：
#   1. 检查这台机器是不是 Steam Frame（风扇 hwmon + 原生温控服务 + CEF 调试端口）
#   2. 把守护进程、前端脚本、systemd 单元装到位
#   3. 启用并启动服务
#   4. 等一会儿，确认它真的连上了 QAM 页面
#
# 任何一步失败都会明确告诉你失败在哪，并且不会把系统留在半装状态。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/device"
[ -d "$SRC" ] || SRC="$HERE"          # 也接受从已解包的安装目录直接跑

DEST="/home/steamos/sf-fan-qam"
UNIT="/etc/systemd/system/sf-fan-qamd.service"
SERVICE="sf-fan-qamd.service"
STOCK="deckard-fan-control.service"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { bad "$*"; exit 1; }

# --------------------------------------------------------------------------
step "1/5  检查权限"
# --------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  die "需要 root：sudo $0"
fi
ok "以 root 运行"

# --------------------------------------------------------------------------
step "2/5  检查这台设备"
# --------------------------------------------------------------------------
[ -d /sys/class/hwmon ] || die "找不到 /sys/class/hwmon，这不是 Linux？"

FAN_DIR=""
for h in /sys/class/hwmon/hwmon*; do
  if [ "$(cat "$h/name" 2>/dev/null)" = "slg4ax46073v" ]; then
    FAN_DIR="$h"
    break
  fi
done

if [ -z "$FAN_DIR" ]; then
  bad "找不到风扇控制器（hwmon 名为 slg4ax46073v）"
  echo "     现有的 hwmon："
  for h in /sys/class/hwmon/hwmon*; do
    [ -f "$h/name" ] && echo "       - $(cat "$h/name")"
  done
  echo "     本面板只适用于 Steam Frame（Deckard）。"
  exit 1
fi
ok "风扇控制器：$FAN_DIR"

if [ ! -e "$FAN_DIR/pwm1" ]; then
  die "$FAN_DIR/pwm1 不存在，无法控制转速"
fi
if ! systemctl list-unit-files "$STOCK" >/dev/null 2>&1 \
   && ! systemctl cat "$STOCK" >/dev/null 2>&1; then
  warn "没找到原生温控服务 $STOCK"
  warn "面板仍然可用，但「自动温控」开关将无法交回系统控制"
else
  ok "原生温控服务 $STOCK 存在"
fi

if ! (echo > /dev/tcp/127.0.0.1/8080) >/dev/null 2>&1; then
  warn "127.0.0.1:8080 现在没有在监听（SteamVR 可能没运行）"
  warn "没关系：守护进程会一直重试，等 GamepadUI 起来就会自动接上"
else
  ok "CEF 调试端口 127.0.0.1:8080 可连接"
fi

command -v python3 >/dev/null || die "找不到 python3"
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
ok "python3 $PYV"

for f in sf_fan_qam.js sf_fan_qamd.py sf-fan-qamd.service; do
  [ -f "$SRC/$f" ] || die "安装包不完整，缺少 $SRC/$f"
done
ok "安装包完整"

# --------------------------------------------------------------------------
step "3/5  复制文件到 $DEST"
# --------------------------------------------------------------------------
# 找出真正跑 Steam 的那个用户（steamwebhelper 的属主）
OWNER="$(ps -eo user:32,args 2>/dev/null | awk '/steamwebhelper/ && !/awk/ {print $1; exit}')"
OWNER="${OWNER:-steamos}"
if ! id "$OWNER" >/dev/null 2>&1; then
  warn "用户 $OWNER 不存在，改用 root 拥有这些文件"
  OWNER="root"
fi

install -d -o "$OWNER" -g "$OWNER" "$DEST"

copy() {  # copy <文件名> <权限> <属主>
  local src="$SRC/$1" mode="$2" own="$3" dst="$DEST/$1"
  if [ "$(readlink -f "$src")" = "$(readlink -f "$dst" 2>/dev/null || echo "$dst")" ]; then
    chmod "$mode" "$dst"
  else
    install -m "$mode" -o "$own" -g "$own" "$src" "$dst"
  fi
  ok "$1  ($mode, $own)"
}

copy sf_fan_qam.js          0644 "$OWNER"
copy sf_fan_qamd.py         0755 root
copy sf-fan-qamd.service    0644 root

install -m 0644 "$SRC/sf-fan-qamd.service" "$UNIT"
# 单元里写死了 /home/steamos/sf-fan-qam；如果装到别处就整体改掉
sed -i "s#/home/steamos/sf-fan-qam#$DEST#g" "$UNIT"
ok "单元已写入 $UNIT"

# 顺手把文档也带上，方便在设备上查
for extra in README.md VERSION; do
  [ -f "$HERE/$extra" ] || continue
  install -m 0644 -o "$OWNER" -g "$OWNER" "$HERE/$extra" "$DEST/$extra"
  ok "$extra"
done
if [ -d "$HERE/docs" ]; then
  install -d -o "$OWNER" -g "$OWNER" "$DEST/docs"
  cp -a "$HERE/docs/." "$DEST/docs/"
  chown -R "$OWNER:$OWNER" "$DEST/docs"
  ok "docs/（技术文档与调试脚本）"
fi

# --------------------------------------------------------------------------
step "4/5  启用并启动服务"
# --------------------------------------------------------------------------
# 安装前如果它已经在跑，先停掉，避免两个实例抢 pwm1
systemctl stop "$SERVICE" 2>/dev/null || true

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl start "$SERVICE"
ok "已启用并启动"

# --------------------------------------------------------------------------
step "5/5  确认它真的接上了 QAM"
# --------------------------------------------------------------------------
ATTACHED=0
for i in $(seq 1 15); do
  sleep 1
  if journalctl -u "$SERVICE" --no-pager -o cat --since "-20 s" 2>/dev/null \
       | grep -q "inject ->"; then
    ATTACHED=1
    break
  fi
done

if ! systemctl is-active --quiet "$SERVICE"; then
  bad "服务没有保持运行，最近日志："
  journalctl -u "$SERVICE" -n 25 --no-pager -o cat | sed 's/^/     /'
  exit 1
fi
ok "服务运行中"

if [ "$ATTACHED" = "1" ]; then
  ok "已注入 QAM 页面（$(journalctl -u "$SERVICE" -o cat --since '-60 s' \
        | grep -o 'inject -> [0-9a-f]*' | tail -1)）"
else
  warn "服务在跑，但还没注入成功——通常是 SteamVR / GamepadUI 没启动"
  warn "启动 SteamVR 后它会在几秒内自动接上，不用重装"
  echo "     最近日志："
  journalctl -u "$SERVICE" -n 8 --no-pager -o cat | sed 's/^/     /'
fi

cat <<'EOF'

────────────────────────────────────────────────────────────
 安装完成

 戴上头显，打开快速设置菜单（点底栏的电池图标），
 在「?」帮助气泡右边应该多出一个风扇图标。

    journalctl -u sf-fan-qamd.service -f   查看实时日志
    sudo ./uninstall.sh                    卸载并恢复系统温控

 如果风扇图标没出现，先跑：
    sudo ./diagnose.sh
────────────────────────────────────────────────────────────
EOF
