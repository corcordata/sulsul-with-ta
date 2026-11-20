"""全程测试：假游戏（真 mod，Python 3.7）→ 真的小转发程序 → 真的服务器 → 假装是 AI（接口 + MCP）+ 假装是自家服务器收推送。
不用 Windows、不用游戏。真游戏里才走得到的那几步（按截图键、占快捷键、切输入法、缩窗口静音）这里测不到。

用法（在仓库根目录）：
  PY37=/path/to/python3.7 server/.venv/bin/python tests/e2e.py
先要打好 dist/mod/SimsLink.ts4script（./build_mod.sh），本机要有 dotnet（编小转发程序）。
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "tests"))

import httpx  # noqa: E402
from PIL import Image  # noqa: E402
from test_app import _Catcher, _free_port, _h  # noqa: E402

PY37 = os.environ.get("PY37", "python3.7")
MOD, AI = "e2e-mod-key", "e2e-ai-key"
BRIDGE_PORT = 47931


def step(text):
    print("  ✓ " + text, flush=True)


def build_bridge(out: Path) -> Path:
    arch = "osx-arm64" if os.uname().machine == "arm64" else ("osx-x64" if sys.platform == "darwin" else "linux-x64")
    done = subprocess.run(["dotnet", "build", str(ROOT / "bridge"), "-c", "Release", "-r", arch, "-o", str(out),
                           "-p:PublishSingleFile=false", "-p:PublishTrimmed=false", "--nologo", "-v", "q"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return out / "SimsLinkBridge"


def game_folder(tmp: Path) -> tuple[Path, Path]:
    """照真的样子摆：…/The Sims 4/Mods/SimsLink/SimsLink.ts4script，旁边是截图文件夹。"""
    sims = tmp / "The Sims 4"
    mod = sims / "Mods" / "SimsLink"
    mod.mkdir(parents=True)
    shutil.copy(ROOT / "dist" / "mod" / "SimsLink.ts4script", mod)
    (sims / "Screenshots").mkdir()
    Image.new("RGB", (640, 360), (40, 40, 40)).save(sims / "Screenshots" / "old.png")
    return sims, mod / "SimsLink.ts4script"


def run_game(script: str, ts4: Path, seconds: float, *more) -> subprocess.Popen:
    return subprocess.Popen([PY37, str(ROOT / "tests" / script), str(ts4), str(seconds), *more],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


async def play_ai(base: str, catcher: _Catcher) -> None:
    from mcp import Client

    async with httpx.AsyncClient(timeout=40) as http:
        async def do(op, **args):
            res = await http.post(base + "/sims/do", json={"op": op, "args": args}, headers=_h(AI))
            assert res.status_code == 200, res.text
            return res.json()

        push = await asyncio.to_thread(catcher.wait, "say", 15)
        assert push["said"] == "你在干嘛" and "林澈（你）" in push["text"] and "林小椴（她" in push["text"], push["text"]
        step("玩家在游戏里说话 → 推到了自家服务器，带着游戏当时的样子")

        now = (await http.get(base + "/sims/now", headers=_h(AI))).json()
        assert now["live"] and "她在游戏里说：「你在干嘛」" in now["text"] and "林团子：不在这块地上" in now["text"]
        assert (await do("say", text="过来，让我抱一下。")) == {"ok": True, "text": "她屏幕右上角弹出来了。"}
        asked = await do("say", text="晚饭想吃什么？", reply=True)
        assert asked["ok"] and "输入框" in asked["text"]
        push = await asyncio.to_thread(catcher.wait, "say", 10)
        assert push["said"] == "我在做饭呀" and "接着上一句" in push["text"] or "跟上一句时一样" in push["text"], push["text"]
        step("AI 看、说话、弹输入框问她；她在框里回的话又推了回来（第二句只带变了的）")

        listed = await do("list", target="小椴")
        assert listed["ok"] and "亲吻" in listed["text"], listed
        kissed = await do("do", target="小椴", name="亲吻")
        assert kissed["ok"] and "排上了" in kissed["text"], kissed
        assert "object_Fridge_Modern" in (await do("objects"))["text"]
        assert "睡衣" in (await do("outfit"))["text"]
        assert (await do("outfit", name="睡衣"))["ok"]
        paid = await do("money", amount=2000, text="去买那个沙发")
        assert paid["ok"] and "§2,000" in paid["text"], paid
        cards = await do("moodlets")
        assert cards["ok"] and "初吻" in cards["text"], cards
        step("AI 操控小人：列动作（中文名来自假字库）、亲吻、看物件、换睡衣、打钱、看情绪卡片")

        out = (await http.post(base + "/sims/reply", headers=_h(AI),
                               json={"text": "我先去躺着等你。⟪小人:睡觉 → Bed⟫"})).json()
        assert out == {"ok": True, "text": "我先去躺着等你。", "marks": 1, "shown": 1}, out
        now = ""
        for _ in range(24):          # 中文名头一回用，游戏那头要先去查字库，服务器隔几秒自动再排一次
            now = (await http.get(base + "/sims/now", headers=_h(AI))).json()["text"]
            if "你用记号排的" in now:
                break
            await asyncio.sleep(0.5)
        assert "你用记号排的「睡觉 → Bed」：林澈 排上了" in now, now
        assert "还没看过" not in now         # 接了推送的，她说的话已经推过了，look 里不再提一遍
        step("回话交给 /sims/reply：⟪小人:睡觉 → Bed⟫ 摘掉并排上了，正文弹进了游戏")

        async with Client(f"{base}/mcp/{AI}") as client:
            look = await client.call_tool("sims", {"action": "look"})
            assert "林澈（你）" in look.content[0].text
            shot = await client.call_tool("sims", {"action": "photo", "text": "留一张"})
            assert [c.type for c in shot.content] == ["text", "image"], shot.content[0].text
            assert len(shot.content[1].data) > 500
        step("MCP 连接器：look 看得到；photo 让转发程序「按了快门」，图直接交到 AI 手里")

        push = await asyncio.to_thread(catcher.wait, "photo", 20)
        picture = await http.get(push["images"][0])
        assert picture.status_code == 200 and picture.content[:2] == b"\xff\xd8"
        step("玩家 ta pic 发截图 → 推送里带着能打开的图片链接")

        push = await asyncio.to_thread(catcher.wait, "wake", 20)
        assert "游戏叫你" in push["text"] and "Bella" in push["text"], push["text"]
        step("她的小人去亲 Bella → 游戏自己来叫 AI")

        assert (await do("speed", speed="2"))["ok"]
        assert "取消了" in (await do("cancel"))["text"]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="simslink-e2e-"))
    procs = []
    try:
        print("编小转发程序、摆假游戏文件夹…", flush=True)
        bridge = build_bridge(tmp / "bridge")
        sims, ts4 = game_folder(tmp)
        game_dir = tmp / "game"
        subprocess.run([sys.executable, str(ROOT / "tests" / "make_strings.py"), str(game_dir), str(sims / "Mods")],
                       check=True, capture_output=True)
        fake_shot = tmp / "fake.png"
        Image.new("RGB", (1920, 1080), (120, 160, 90)).save(fake_shot)

        catcher = _Catcher()
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        env = dict(os.environ, PYTHONPATH=str(ROOT / "server"), SIMSLINK_DATA=str(tmp / "data"), SIMSLINK_PORT=str(port),
                   SIMSLINK_HOST="127.0.0.1", SIMSLINK_MOD_TOKEN=MOD, SIMSLINK_AI_TOKEN=AI, SIMSLINK_PUBLIC_URL=base,
                   SIMSLINK_WEBHOOK_URL=f"http://127.0.0.1:{catcher.port}/hook", SIMSLINK_REPLY_MIRROR="1",
                   SIMSLINK_PLAYER_PRONOUN="她", PYTHONUNBUFFERED="1")
        server = subprocess.Popen([sys.executable, "-m", "simslink_server"], cwd=tmp, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(server)
        for _ in range(100):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("服务器没起来")

        (bridge.parent / "SimsLinkBridge.cfg").write_text(json.dumps({"server": base, "token": MOD, "port": BRIDGE_PORT}))
        bridge_log = open(tmp / "bridge.log", "w")
        procs.append(subprocess.Popen([str(bridge)], stdout=bridge_log, stderr=subprocess.STDOUT,
                                      env=dict(os.environ, SIMSLINK_FAKE_SHOT=str(fake_shot), SIMSLINK_GAME_DIR=str(game_dir))))
        text = ""
        for _ in range(60):                      # 头一回开要几秒
            text = (tmp / "bridge.log").read_text()
            if "等游戏来敲门" in text:
                break
            time.sleep(0.25)
        assert "服务器连得上 ✓" in text, text
        step("小转发程序打开，用游戏那把钥匙连上了服务器")

        print("第一场：说话、操控、拍照、叫醒（约 35 秒）", flush=True)
        game = run_game("e2e_game.py", ts4, 34)
        asyncio.run(play_ai(base, catcher))
        out, err = game.communicate(timeout=60)
        assert game.returncode == 0, err
        seen = json.loads(out.strip().splitlines()[-1])
        notes = [(n[0], n[1]) for n in seen["notifications"]]
        console = "\n".join(seen["console"])
        assert any("还没告诉我哪个小人是 TA" in n[1] for n in notes), notes
        assert "还没设（ta ai 名字）" in console and "家里没有名字带「不存在」的小人" in console
        assert "记下了：TA 的小人是名字带「澈」的那个。" in console and "TA 的小人：澈｜我的小人：小椴" in console
        step("头一回进游戏会提醒设小人；ta ai / ta me 记下了，写错名字会告诉她家里有谁")
        assert ("林澈", "过来，让我抱一下。") in notes and ("林澈", "我先去躺着等你。") in notes, notes
        assert ("林澈", "给你转了 §2,000：去买那个沙发") in notes
        assert ("林澈", "晚饭想吃什么？") in [tuple(d) for d in seen["dialogs"]]
        assert any("发给 TA 了，1 张" in n[1] for n in notes), notes
        step("游戏这头：AI 的话弹出来了，标题是 TA 小人的名字；打钱、截图的回执都在")
        did = [(who, act) for who, act, _target in seen["executed"]]
        assert ("澈", "mixer_social_Kiss_targeted_romance") in did and ("澈", "bed_Sleep") in did, seen["executed"]
        assert seen["his_outfit"][0] == 3, seen["his_outfit"]          # 3 = 睡衣那一类
        assert all("cancelled" in item for item in seen["his_queue"]), seen["his_queue"]
        step("小人真的排上了亲吻和睡觉，换上了睡衣，最后 cancel 全清掉了")
        names = json.loads((sims / "Mods" / "SimsLink" / "SimsLink.cfg").read_text(encoding="utf-8"))
        assert names["ai_names"] == ["澈"] and names["player_names"] == ["小椴"], names

        print("第二场：快捷键说话、换键、老板键（约 13 秒）", flush=True)
        key = run_game("e2e_key_game.py", ts4, 13)
        out, err = key.communicate(timeout=40)
        assert key.returncode == 0 and out.strip().endswith("OK 1.0.0"), out[-800:] + err[-1500:]
        push = catcher.wait("say", 5)
        assert push["said"] == "我在这呢"
        step("按快捷键弹框不叠框、她打的字送到了、换键、两个键不能相同、老板键暂停了游戏")

        log = (tmp / "bridge.log").read_text()
        assert "字库" in log and "有表读不了" in log, log     # 假字库里故意放了一张坏表
        print("\n全程通过。小转发程序的黑窗口里写的是：\n" + "\n".join("    " + line for line in log.splitlines()[:40]))
        return 0
    finally:
        for proc in procs:
            proc.kill()
        if os.environ.get("KEEP_E2E") != "1":
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print("留着了：", tmp)


if __name__ == "__main__":
    sys.exit(main())
