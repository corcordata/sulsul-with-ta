#!/bin/sh
# 还没有服务器、想先在真游戏里试一下：在同一个 Wi-Fi 里的另一台电脑（Mac / Linux）上临时开服务。
# 玩游戏那台电脑的 SulSulBridge.cfg 照它印出来的填。只在家里的局域网用：这样走的是 http，没有加密。
# 用法：tests/try_on_lan.sh        （要先 cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt）
set -e
cd "$(dirname "$0")/../server"
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
test -n "$IP" || { echo "找不到这台电脑在局域网里的地址"; exit 1; }
export SULSUL_PORT="${SULSUL_PORT:-8787}"
export SULSUL_PUBLIC_URL="http://$IP:$SULSUL_PORT"
export SULSUL_DATA="${SULSUL_DATA:-$PWD/data-lan-test}"
.venv/bin/python -m sulsul_server info
echo
exec .venv/bin/python -m sulsul_server
