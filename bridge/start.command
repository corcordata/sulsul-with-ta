#!/bin/sh
# Mac 上开小转发程序。
# 打开「终端」，输入 sh 加一个空格，把这个文件拖进终端窗口，回车。
# （直接双击会被 macOS 拦下来，因为这个程序没有花钱买苹果的签名。）
cd "$(dirname "$0")" || exit 1
xattr -dr com.apple.quarantine . 2>/dev/null
chmod +x SulSulBridge-arm64 SulSulBridge-x64 2>/dev/null
if [ "$(uname -m)" = "arm64" ]; then
  exec ./SulSulBridge-arm64
else
  exec ./SulSulBridge-x64
fi
