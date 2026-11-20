"""把服务器真的开起来，从三扇门各走一遍：游戏（假 mod）、AI（接口 + MCP）、往外的推送。"""
import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
MOD, AI = "mod-test-key", "ai-test-key"

STATE = {
    "zone": {"lot": "柳溪小屋", "home": True},
    "clock": {"day": 3, "hour": 14, "minute": 5, "speed": "NORMAL"},
    "sims": [
        {"name": "阿澈", "here": True, "his": True, "doing": [{"name": "sofa_Sit"}], "motives": {"Hunger": 10}},
        {"name": "小椴", "here": True, "hers": True, "active": True, "doing": [], "motives": {"Hunger": 20}},
    ],
    "others": [], "street": {"n": 0, "names": []},
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Catcher:
    """假装是玩家自家的服务器：收推送，记下来。"""

    def __init__(self):
        self.got: list[dict] = []
        self.auth: list[str] = []
        catcher = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                catcher.got.append(json.loads(body))
                catcher.auth.append(self.headers.get("Authorization") or "")
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        self.port = _free_port()
        self.httpd = HTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def wait(self, kind: str, timeout: float = 5.0) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            for item in self.got:
                if item.get("kind") == kind:
                    self.got.remove(item)
                    return item
            time.sleep(0.05)
        raise AssertionError(f"没等到 {kind} 的推送，收到的有：{[g.get('kind') for g in self.got]}")


def _start(tmp_path, **extra):
    port = _free_port()
    env = dict(os.environ, SIMSLINK_DATA=str(tmp_path / "data"), SIMSLINK_PORT=str(port), SIMSLINK_HOST="127.0.0.1",
               SIMSLINK_MOD_TOKEN=MOD, SIMSLINK_TA_TOKEN=AI, SIMSLINK_PUBLIC_URL=f"http://127.0.0.1:{port}",
               PYTHONUNBUFFERED="1")
    for key in ("SIMSLINK_WEBHOOK_URL", "SIMSLINK_WEBHOOK_TOKEN", "SIMSLINK_REPLY_MIRROR", "SIMSLINK_PLAYER_PRONOUN"):
        env.pop(key, None)
    env.update(extra)
    proc = subprocess.Popen([sys.executable, "-m", "simslink_server"], cwd=tmp_path, env=dict(env, PYTHONPATH=str(SERVER_DIR)),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health", timeout=1).status_code == 200:
                return proc, base
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("服务器没起来：\n" + proc.stdout.read().decode())


@pytest.fixture
def wired(tmp_path):
    """接全了的那种：有推送地址，回话也交给 /sims/reply。"""
    catcher = _Catcher()
    proc, base = _start(tmp_path, SIMSLINK_WEBHOOK_URL=f"http://127.0.0.1:{catcher.port}/hook",
                        SIMSLINK_WEBHOOK_TOKEN="hook-key", SIMSLINK_REPLY_MIRROR="1")
    yield base, catcher
    proc.kill()
    catcher.httpd.shutdown()


@pytest.fixture
def bare(tmp_path):
    """只加了 MCP 连接器的那种：没有推送，回话也没接。"""
    proc, base = _start(tmp_path)
    yield base
    proc.kill()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


class FakeMod:
    """假装是游戏里的 mod：每趟交状态 / 事件 / 结果，领指令，「做完」把结果交回去。"""

    def __init__(self, base):
        self.base, self.after, self.results, self.seen = base, 0, [], []
        self.stop = False

    async def once(self, client, wait=0.0, **body):
        payload = dict({"v": 1, "after": self.after, "wait": wait, "screen": "live", "events": [], "results": self.results}, **body)
        self.results = []
        res = await client.post(self.base + "/sims/mod/sync", json=payload, headers=_h(MOD), timeout=10)
        assert res.status_code == 200, res.text
        for cmd in res.json()["commands"]:
            self.after = max(self.after, cmd["id"])
            self.seen.append(cmd)
            args = cmd["args"]
            text = {"say": "她屏幕右上角弹出来了。", "do": "阿澈 排上了：%s" % args.get("name"),
                    "outfit": "换上了%s。" % args.get("name")}.get(cmd["op"], "好了：%s" % cmd["op"])
            self.results.append({"id": cmd["id"], "ok": True, "text": text})
        return res.json()

    async def run(self, client):
        while not self.stop:
            await self.once(client, wait=0.3)


def test_all_three_doors_when_fully_wired(wired):
    base, catcher = wired

    async def go():
        async with httpx.AsyncClient() as client:
            # 钥匙：没带 / 带错 / 游戏的钥匙想碰 AI 的门，全挡在外面
            assert (await client.post(base + "/sims/mod/sync", json={"probe": True})).status_code == 401
            assert (await client.get(base + "/sims/now", headers=_h(MOD))).status_code == 401
            assert (await client.post(base + "/sims/do", json={"op": "say", "args": {"text": "x"}}, headers=_h("nope"))).status_code == 401
            assert (await client.post(base + "/mcp", json={})).status_code == 401
            assert (await client.post(base + "/mcp/wrong", json={})).status_code == 401
            assert (await client.post(base + "/sims/mod/sync", json={"probe": True}, headers=_h(MOD))).json()["ok"]

            mod = FakeMod(base)
            await mod.once(client, state=STATE)
            # 她在游戏里说话 → 推给自家服务器，带着钥匙，字是拼好的
            await mod.once(client, events=[{"t": "say", "text": "你在干嘛"}])
            push = catcher.wait("say")
            assert push["said"] == "你在干嘛" and "「你在干嘛」" in push["text"] and "柳溪小屋" in push["text"]
            assert "自动弹在她游戏右上角" in push["text"] and catcher.auth[-1] == "Bearer hook-key"

            pump = asyncio.create_task(mod.run(client))
            try:
                # AI 看 / 说 / 做（接口）
                now = (await client.get(base + "/sims/now", headers=_h(AI))).json()
                assert now["live"] and "阿澈（你）" in now["text"] and "她在游戏里说：「你在干嘛」" in now["text"]
                said = (await client.post(base + "/sims/do", json={"op": "say", "args": {"text": "过来抱一下"}}, headers=_h(AI))).json()
                assert said == {"ok": True, "text": "她屏幕右上角弹出来了。"}
                bad = await client.post(base + "/sims/do", json={"op": "run_python", "args": {}}, headers=_h(AI))
                assert bad.status_code == 400

                # 回话交进来：记号摘掉交给游戏，正文弹进游戏
                out = (await client.post(base + "/sims/reply", headers=_h(AI),
                                         json={"text": "来了。⟪小人:亲吻 → 小椴⟫\n先换件衣服 ⟪小人:穿 睡衣⟫"})).json()
                assert out["text"] == "来了。\n先换件衣服" and out["marks"] == 2 and out["shown"] == 1
                await asyncio.sleep(1.0)
                ops = [(c["op"], c["args"]) for c in mod.seen]
                assert ("do", {"name": "亲吻", "target": "小椴"}) in ops and ("outfit", {"name": "睡衣"}) in ops
                assert ("say", {"text": "来了。\n先换件衣服"}) in ops
                now = (await client.get(base + "/sims/now", headers=_h(AI))).json()["text"]
                assert "你用记号排的「亲吻 → 小椴」：阿澈 排上了：亲吻" in now and "你在游戏里说：「来了。" in now

                # 截图：她发来的 → 推送里带链接，链接真能打开
                from PIL import Image
                png = io.BytesIO()
                Image.new("RGB", (800, 450), (90, 140, 200)).save(png, format="PNG")
                up = await client.post(base + "/sims/mod/photo?by=her&hold=0&caption=新裙子", content=png.getvalue(), headers=_h(MOD))
                assert up.json() == {"ok": True, "posted": 1}
                push = catcher.wait("photo")
                assert "1 张截图" in push["text"] and "「新裙子」" in push["text"] and len(push["images"]) == 1
                picture = await client.get(push["images"][0])
                assert picture.status_code == 200 and picture.headers["content-type"] == "image/jpeg"
                assert (await client.get(base + "/photos/../tokens.json")).status_code == 404
            finally:
                mod.stop = True
                await pump

            # 游戏叫醒：她的小人去亲别人 → 推一条 wake
            kissing = json.loads(json.dumps(STATE))
            kissing["others"] = ["Tom"]
            kissing["sims"][1]["doing"] = [{"name": "mixer_social_Kiss_targeted_romance", "target": "Tom"}]
            await mod.once(client, state=kissing, events=[
                {"t": "act", "who": "小椴", "name": "mixer_social_Kiss_targeted_romance", "target": "Tom"}])
            push = catcher.wait("wake")
            assert "游戏叫你" in push["text"] and "Tom 不是你" in push["text"] and push["reasons"]

    asyncio.run(go())


def test_mcp_only_setup(bare):
    """只加 MCP 连接器：用带钥匙的地址连，工具能看、能说、能拿到她发来的截图；提示语不说「会自动弹」。"""
    base = bare

    async def go():
        from mcp import Client

        async with httpx.AsyncClient() as http:
            mod = FakeMod(base)
            await mod.once(http, state=STATE, events=[{"t": "say", "text": "在吗"}])
            from PIL import Image
            png = io.BytesIO()
            Image.new("RGB", (640, 360), (200, 90, 90)).save(png, format="PNG")
            await http.post(base + "/sims/mod/photo?by=her&hold=0", content=png.getvalue(), headers=_h(MOD))
            pump = asyncio.create_task(mod.run(http))
            try:
                async with Client(f"{base}/mcp/{AI}") as client:
                    tools = (await client.list_tools()).tools
                    assert [t.name for t in tools] == ["sims"]
                    assert "action=say" in tools[0].description and "自动弹" not in tools[0].description
                    assert set(tools[0].input_schema["properties"]["action"]["enum"]) >= {"look", "say", "do", "photo"}

                    look = await client.call_tool("sims", {"action": "look"})
                    kinds = [c.type for c in look.content]
                    text = look.content[0].text
                    assert kinds == ["text", "image"], kinds
                    assert "对你说了 1 句你还没看过的" in text and "「在吗」" in text and "发来 1 张截图" in text
                    assert "阿澈（你）" in text

                    again = await client.call_tool("sims", {"action": "look"})
                    assert [c.type for c in again.content] == ["text"] and "还没看过" not in again.content[0].text

                    said = await client.call_tool("sims", {"action": "say", "text": "在。刚看到。"})
                    assert said.content[0].text == "她屏幕右上角弹出来了。"
                    done = await client.call_tool("sims", {"action": "do", "target": "小椴", "name": "拥抱"})
                    assert "排上了：拥抱" in done.content[0].text
                    oops = await client.call_tool("sims", {"action": "do"})
                    assert oops.content[0].text.startswith("没成：")
            finally:
                mod.stop = True
                await pump

    asyncio.run(go())


def test_pronoun_setting_reaches_every_exit(tmp_path):
    proc, base = _start(tmp_path, SIMSLINK_PLAYER_PRONOUN="他")
    try:
        async def go():
            async with httpx.AsyncClient() as http:
                await FakeMod(base).once(http, state=STATE, events=[{"t": "say", "text": "她是谁"}])
                text = (await http.get(base + "/sims/now", headers=_h(AI))).json()["text"]
                assert "他正在玩" in text and "他在游戏里说：「她是谁」" in text and "她正" not in text

        asyncio.run(go())
    finally:
        proc.kill()
