#!/bin/sh
# 打出给人下载的两个压缩包：dist/SimsLink-<版本>-windows.zip 和 -mac.zip
# 先要有：
#   dist/mod/SimsLink.ts4script                 ./build_mod.sh
#   build/bridge-win/SimsLinkBridge.exe          cd bridge && dotnet publish -c Release -r win-x64   -o ../build/bridge-win
#   build/bridge-mac-arm64/SimsLinkBridge        cd bridge && dotnet publish -c Release -r osx-arm64 -o ../build/bridge-mac-arm64
#   build/bridge-mac-x64/SimsLinkBridge          cd bridge && dotnet publish -c Release -r osx-x64   -o ../build/bridge-mac-x64
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n "s/^VERSION = '\(.*\)'/\1/p" mod/simslink/__init__.py)
test -n "$VERSION" || { echo "读不到版本号"; exit 1; }
for need in dist/mod/SimsLink.ts4script build/bridge-win/SimsLinkBridge.exe \
            build/bridge-mac-arm64/SimsLinkBridge build/bridge-mac-x64/SimsLinkBridge; do
  test -f "$need" || { echo "缺 $need（看这个文件开头的说明）"; exit 1; }
done
mkdir -p dist
STAGE=$(mktemp -d)

common() {      # 两个包里一样的部分
  OUT="$1"
  mkdir -p "$OUT/1-put-into-Mods/SimsLink" "$OUT/3-server/simslink_server"
  cp dist/mod/SimsLink.ts4script "$OUT/1-put-into-Mods/SimsLink/"
  cp server/simslink_server/*.py "$OUT/3-server/simslink_server/"
  cp server/requirements.txt server/.env.example server/Dockerfile server/docker-compose.yml "$OUT/3-server/"
  cp INSTALL.md LICENSE "$OUT/"
  cp docs/ta-manual.md "$OUT/TA-MANUAL.md"
}

cfg() {
  printf '{\n "server": "https://sims.example.com",\n "token": "PASTE-MOD-TOKEN-HERE"\n}\n' > "$1/SimsLinkBridge.cfg"
}

zipup() {
  NAME="$1"
  ZIP="$PWD/dist/$NAME.zip"
  if [ -f "$ZIP" ]; then mv "$ZIP" "$ZIP.old"; fi
  (cd "$STAGE" && zip -q -r -X "$ZIP" "$NAME")
  unzip -l "$ZIP" | tail -1
}

WIN="SimsLink-$VERSION-windows"
common "$STAGE/$WIN"
mkdir -p "$STAGE/$WIN/2-bridge"
cp build/bridge-win/SimsLinkBridge.exe "$STAGE/$WIN/2-bridge/"
cfg "$STAGE/$WIN/2-bridge"
zipup "$WIN"

MAC="SimsLink-$VERSION-mac"
common "$STAGE/$MAC"
mkdir -p "$STAGE/$MAC/2-bridge"
cp build/bridge-mac-arm64/SimsLinkBridge "$STAGE/$MAC/2-bridge/SimsLinkBridge-arm64"
cp build/bridge-mac-x64/SimsLinkBridge "$STAGE/$MAC/2-bridge/SimsLinkBridge-x64"
cp bridge/start.command "$STAGE/$MAC/2-bridge/"
chmod +x "$STAGE/$MAC/2-bridge/"*
cfg "$STAGE/$MAC/2-bridge"
zipup "$MAC"
