"""Claude 桌面版扩展的入口：把本机模式开起来。sulsul_server 这个包是打包时从 server/ 拷进来的。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sulsul_server.local import main  # noqa: E402

main()
