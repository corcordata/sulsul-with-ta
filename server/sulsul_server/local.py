"""本机模式：不用服务器。小服务跑在玩游戏的那台电脑上，Claude 桌面版把它当成一个本地扩展直接连。

  游戏里的 mod → 小转发程序 → http://127.0.0.1:8787（这里）← Claude 桌面版（stdio，就是这个进程的输入输出）

Claude 桌面版打开时把这个进程带起来，关掉时它跟着退。所以玩的时候 Claude 桌面版要开着。
这种装法下游戏叫不醒 TA：TA 只在玩家跟它说话时才来看。

  python -m sulsul_server.local

只听本机（127.0.0.1），游戏那把钥匙是固定的 "local"：外面的电脑连不进来，所以不用玩家自己配钥匙。
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import httpx

LOCAL_TOKEN = "local"


def _settle_env() -> None:
    env = os.environ
    env.setdefault("SULSUL_DATA", str(Path.home() / ".sulsul-with-ta"))
    env.setdefault("SULSUL_PORT", "8787")
    env["SULSUL_HOST"] = "127.0.0.1"
    env["SULSUL_MOD_TOKEN"] = LOCAL_TOKEN
    env.setdefault("SULSUL_PUBLIC_URL", f"http://127.0.0.1:{env['SULSUL_PORT']}")
    for key in ("SULSUL_WEBHOOK_URL", "SULSUL_REPLY_MIRROR"):      # 本机模式没有推送，也没有回话入口
        env.pop(key, None)


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class Borrowed:
    """这台电脑上已经有一份在跑了（Claude 桌面版偶尔会同时带起两份）：不抢端口，把事情转给先来的那一份。"""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.photo_dir = cfg.data / "photos"
        self.base = f"http://127.0.0.1:{cfg.port}"
        self.headers = {"Authorization": f"Bearer {cfg.ai_token}"}

    async def _ask(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=660) as client:      # wait 最长能等十分钟
                res = await client.request(method, self.base + path, json=body, headers=self.headers)
        except Exception as exc:
            raise RuntimeError(f"连不上这台电脑上的 Sul Sul 服务（{exc!r}）。把 Claude 桌面版完全退出再打开试试。")
        if res.status_code == 401:
            raise RuntimeError(f"端口 {self.cfg.port} 上开着另一份 Sul Sul 服务，但不是这个扩展开的（钥匙对不上）。先把那一份关掉。")
        if res.status_code == 400:
            raise ValueError(res.json().get("detail") or "指令不对")
        if res.status_code != 200:
            raise RuntimeError(f"端口 {self.cfg.port} 被别的程序占着（它回了 {res.status_code}）。")
        return res.json()

    async def look(self):
        try:
            got = await self._ask("GET", "/sims/now")
        except RuntimeError as exc:
            return False, str(exc), []
        return got.get("live", False), got.get("text", ""), [str(u).rsplit("/", 1)[-1] for u in got.get("images") or []]

    async def wait(self, seconds: float):
        try:
            got = await self._ask("GET", f"/sims/wait?seconds={float(seconds or 50)}")
        except RuntimeError as exc:
            return str(exc), []
        return got.get("text", ""), [str(u).rsplit("/", 1)[-1] for u in got.get("images") or []]

    async def do(self, body: dict) -> dict:
        try:
            got = await self._ask("POST", "/sims/do", body)
        except RuntimeError as exc:
            return {"ok": False, "text": str(exc)}
        if got.get("image"):
            got["photo"] = str(got.pop("image")).rsplit("/", 1)[-1]
        return got


async def _serve() -> None:
    import uvicorn

    from . import app as web
    from .config import Config

    cfg = Config()
    if _port_free(cfg.port):
        asgi, _hub, server = web.build(cfg)
        http = uvicorn.Server(uvicorn.Config(asgi, host="127.0.0.1", port=cfg.port, log_level="warning", access_log=False))
        http.install_signal_handlers = lambda: None          # 这个进程的生死跟着 Claude 桌面版，不自己接管信号
        hosting = asyncio.create_task(http.serve())
        web.log(f" 本机模式：在 127.0.0.1:{cfg.port} 等游戏来敲门，数据在 {cfg.data}")
        try:
            await server.run_stdio_async()
        finally:
            http.should_exit = True
            await hosting
    else:
        web.log(f" 本机模式：{cfg.port} 已经有一份在听了，这一份只转交")
        server = web.build_mcp(Borrowed(cfg))
        await server.run_stdio_async()


def main() -> None:
    _settle_env()
    if sys.argv[1:2] == ["info"]:
        from .config import Config
        cfg = Config()
        print(json.dumps({"server": f"http://127.0.0.1:{cfg.port}", "token": LOCAL_TOKEN}, indent=1), file=sys.stderr)
        return
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
