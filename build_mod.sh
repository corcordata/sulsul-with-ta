#!/bin/sh
# 把 mod/sulsul 编成 Python 3.7 的 .pyc，打成 dist/mod/SulSul.ts4script。
# Sims 4 自带的 Python 是 3.7，别的版本编出来的 .pyc 游戏不认。
# 用法：PY37=/path/to/python3.7 ./build_mod.sh
set -e
cd "$(dirname "$0")"
PY37="${PY37:-python3.7}"
"$PY37" -c 'import sys; assert sys.version_info[:2] == (3, 7), "要 Python 3.7，现在是 %s" % sys.version'
rm -rf build/mod dist/mod && mkdir -p build/mod dist/mod
cp -R mod/sulsul build/mod/
find build/mod -name "__pycache__" -prune -exec rm -rf {} \;
"$PY37" -m compileall -q -b build/mod/sulsul
find build/mod -name "*.py" -delete
(cd build/mod && zip -q -r ../../dist/mod/SulSul.ts4script sulsul)
unzip -l dist/mod/SulSul.ts4script | tail -3
