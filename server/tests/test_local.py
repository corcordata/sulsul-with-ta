"""本机模式：像 Claude 桌面版那样用 stdio 把服务带起来，同时假装游戏从本机端口敲门。"""
import asyncio
import os
import sys
from pathlib import Path

import httpx

from test_app import STATE, FakeMod, _free_port

SERVER_DIR = Path(__file__).resolve().parents[1]


def _params(tmp_path, port):
    from mcp import StdioServerParameters

    env = {k: v for k, v in os.environ.items() if not k.startswith("SULSUL_")}
    env.update(PYTHONPATH=str(SERVER_DIR), SULSUL_DATA=str(tmp_path / "data"), SULSUL_PORT=str(port),
               SULSUL_WEBHOOK_URL="http://should-be-ignored.invalid/")      # 本机模式不推送：填了也要被忽略
    return StdioServerParameters(command=sys.executable, args=["-m", "sulsul_server.local"], env=env, cwd=str(tmp_path))


def test_desktop_app_talks_over_stdio_while_the_game_knocks_on_localhost(tmp_path):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    async def go():
        from mcp import Client

        async with Client(_params(tmp_path, port)) as client:
            tools = (await client.list_tools()).tools
            assert [t.name for t in tools] == ["sims"]
            assert "action=say" in tools[0].description and "自动弹" not in tools[0].description
            manual = await client.call_tool("sims", {"action": "manual"})
            assert "操控你的小人" in manual.content[0].text and "ta who" in manual.content[0].text

            async with httpx.AsyncClient() as http:
                for _ in range(50):
                    try:
                        if (await http.get(base + "/health")).status_code == 200:
                            break
                    except Exception:
                        await asyncio.sleep(0.1)
                # 游戏那把钥匙是固定的 local；别的钥匙进不来
                mod = FakeMod(base)
                bad = await http.post(base + "/sims/mod/sync", json={"probe": True}, headers={"Authorization": "Bearer nope"})
                assert bad.status_code == 401
                import test_app
                test_app.MOD, kept = "local", test_app.MOD
                try:
                    await mod.once(http, state=STATE, events=[{"t": "say", "text": "在吗"}])
                    pump = asyncio.create_task(mod.run(http))
                    try:
                        look = await client.call_tool("sims", {"action": "look"})
                        text = look.content[0].text
                        assert "阿澈（你）" in text and "对你说了 1 句你还没看过的" in text and "「在吗」" in text
                        said = await client.call_tool("sims", {"action": "say", "text": "在。"})
                        assert said.content[0].text == "她屏幕右上角弹出来了。"

                        # 第二份（Claude 桌面版偶尔会同时带起两份）：不抢端口，转给第一份
                        async with Client(_params(tmp_path, port)) as second:
                            again = await second.call_tool("sims", {"action": "look"})
                            assert "阿澈（你）" in again.content[0].text
                            done = await second.call_tool("sims", {"action": "do", "target": "小椴", "name": "拥抱"})
                            assert "排上了：拥抱" in done.content[0].text
                            oops = await second.call_tool("sims", {"action": "do"})
                            assert oops.content[0].text.startswith("没成：")
                    finally:
                        mod.stop = True
                        await pump
                finally:
                    test_app.MOD = kept
        # Claude 桌面版一关，本机的服务也跟着退
        await asyncio.sleep(0.5)
        async with httpx.AsyncClient() as http:
            try:
                await http.get(base + "/health", timeout=1)
                raise AssertionError("桌面版关了，服务还开着")
            except httpx.HTTPError:
                pass

    asyncio.run(go())
