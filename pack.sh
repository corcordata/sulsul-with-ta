#!/bin/sh
# 打出给人下载的压缩包：dist/SimsLink-<版本>.zip
# 先要有 dist/mod/SimsLink.ts4script（./build_mod.sh）和 build/bridge-win/SimsLinkBridge.exe（dotnet publish，见 README）。
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n "s/^VERSION = '\(.*\)'/\1/p" mod/simslink/__init__.py)
test -n "$VERSION" || { echo "读不到版本号"; exit 1; }
NAME="SimsLink-$VERSION"
test -f dist/mod/SimsLink.ts4script || { echo "先跑 ./build_mod.sh"; exit 1; }
test -f build/bridge-win/SimsLinkBridge.exe || { echo "先编小转发程序（README：自己从源码编）"; exit 1; }

STAGE=$(mktemp -d)
OUT="$STAGE/$NAME"
mkdir -p "$OUT/1-put-into-Mods/SimsLink" "$OUT/2-bridge" "$OUT/3-server/simslink_server"
cp dist/mod/SimsLink.ts4script "$OUT/1-put-into-Mods/SimsLink/"
cp build/bridge-win/SimsLinkBridge.exe "$OUT/2-bridge/"
printf '{\n "server": "https://sims.example.com",\n "token": "PASTE-MOD-TOKEN-HERE"\n}\n' > "$OUT/2-bridge/SimsLinkBridge.cfg"
cp server/simslink_server/*.py "$OUT/3-server/simslink_server/"
cp server/requirements.txt server/.env.example server/Dockerfile server/docker-compose.yml "$OUT/3-server/"
cp INSTALL.md LICENSE "$OUT/"
cp docs/ai-manual.md "$OUT/AI-MANUAL.md"

mkdir -p dist
ZIP="$PWD/dist/$NAME.zip"
if [ -f "$ZIP" ]; then mv "$ZIP" "$ZIP.old"; fi
(cd "$STAGE" && zip -q -r -X "$ZIP" "$NAME")
unzip -l "$ZIP"
