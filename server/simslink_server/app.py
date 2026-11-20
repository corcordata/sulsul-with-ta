"""会等的那一半：网络、指令排队、往外推送、MCP。纯逻辑（收什么、怎么写成字）在 core.py。

三拨人来敲门：
  游戏（经玩家电脑上的 SimsLinkBridge）  POST /sims/mod/sync、/sims/mod/photo    带 MOD 钥匙
  AI（MCP）                              /mcp 或 /mcp/<AI 钥匙>                   一个工具：sims
  AI 那头的程序（不走 MCP 的接法）        GET /sims/now、POST /sims/do、/sims/reply 带 AI 钥匙
往外只做一件事：玩家在游戏里说话、游戏里出了事、玩家发来截图时，POST 给 SIMSLINK_WEBHOOK_URL。

全程 asyncio，一个进程；状态和事件落在数据文件夹里，排队的指令只在内存里（25 秒就作废）。
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
import secrets
import time
from typing import Annotated, Literal

import httpx
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import VERSION, core
from .config import Config

PHOTOS_KEEP = 300
_PHOTO_NAME = re.compile(r"^[A-Za-z0-9_-]{20,64}\.jpg$")


def _same(given: str, wanted: str) -> bool:
    return bool(given) and bool(wanted) and hmac.compare_digest(given.encode(), wanted.encode())


def _bearer(headers) -> str:
    auth = headers.get("authorization", "")
    return auth[7:].strip() if auth[:7].lower() == "bearer " else ""


class Hub:
    """游戏和 AI 之间的那张桌子：AI 的指令放上来，游戏下一次敲门时领走，做完把结果放回来。"""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.root = cfg.data / "sims"
        self.photo_dir = cfg.data / "photos"
        self.commands: list[dict] = []
        self.waiters: dict[int, asyncio.Future] = {}
        self.marks: dict[int, dict] = {}          # 用记号排的指令：指令号 → 是哪个记号
        self.shots: dict[int, str] = {}           # AI 拍的照片：指令号 → 文件名
        self.held: list[str] = []                 # 玩家一口气发来的截图，攒到最后一张再一起交
        self.unseen_photos: list[str] = []        # 玩家发来、AI 还没看过的截图
        self.last_id = 0
        self._signal: asyncio.Event | None = None
        self._tasks: set[asyncio.Task] = set()

    # ---- 小工具 ----
    @property
    def signal(self) -> asyncio.Event:
        if self._signal is None:
            self._signal = asyncio.Event()
        return self._signal

    def spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def queue(self, op: str, args: dict) -> int:
        self.last_id = core.next_command_id(self.last_id)
        self.commands.append({"op": op, "args": args, "id": self.last_id, "at": time.time()})
        self.signal.set()
        return self.last_id

    def photo_url(self, name: str) -> str:
        return f"{self.cfg.public_url}/photos/{name}"

    def save_photo(self, jpeg: bytes) -> str:
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        name = secrets.token_urlsafe(24) + ".jpg"
        (self.photo_dir / name).write_bytes(jpeg)
        old = sorted(self.photo_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)[:-PHOTOS_KEEP]
        for path in old:
            try:
                path.unlink()
            except OSError:
                pass
        return name

    # ---- 往外推 ----
    def push(self, kind: str, text: str, **extra) -> None:
        if not self.cfg.webhook_url:
            return
        payload = {"kind": kind, "text": core.voice(text), "at": time.time()}
        payload.update(extra)
        self.spawn(self._post(payload))

    async def _post(self, payload: dict) -> None:
        headers = {"Authorization": f"Bearer {self.cfg.webhook_token}"} if self.cfg.webhook_token else {}
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    res = await client.post(self.cfg.webhook_url, json=payload, headers=headers)
                if res.status_code < 500:
                    if res.status_code >= 400:
                        print(f"[simslink] 推送被拒了（{res.status_code}）：{payload['kind']}", flush=True)
                    return
            except Exception as exc:
                print(f"[simslink] 推送没成（第 {attempt + 1} 次）：{exc!r}", flush=True)
            await asyncio.sleep(2 * (attempt + 1))

    # ---- 游戏来敲门 ----
    async def sync(self, raw: bytes) -> tuple[int, dict]:
        if len(raw) > core.MAX_BODY:
            return 413, {"detail": "too large"}
        try:
            body = json.loads(raw)
            if isinstance(body, dict) and body.get("probe"):
                return 200, {"ok": True, "commands": []}    # 转发程序刚打开时试钥匙；不算「游戏来过」
            sync = core.clean_sync(body)
        except ValueError as exc:
            return 400, {"detail": str(exc)}
        except Exception:
            return 400, {"detail": "bad json"}
        try:
            wake = await asyncio.to_thread(core.wake_plan, self.root, sync)    # 要在存之前问：拿旧状态来比
        except Exception as exc:
            wake = None
            print(f"[simslink] wake_plan failed: {exc!r}", flush=True)
        await asyncio.to_thread(core.record, self.root, sync)
        for result in sync["results"]:
            try:
                cid = int(result["id"])
            except (TypeError, ValueError):
                continue
            # 做完的指令当场划掉：游戏重开后（它记的「收到第几条」归零）不会把刚做过的再领一遍
            self.commands = [c for c in self.commands if c["id"] != cid]
            waiter = self.waiters.pop(cid, None)
            if waiter is not None and not waiter.done():
                waiter.set_result(result)
            mark = self.marks.pop(cid, None)
            if mark is not None:
                self.spawn(self._mark_done(mark, result))
        if self.cfg.webhook_url:
            for said in core.her_says(sync):
                note = await asyncio.to_thread(core.note_for_him, self.root)
                self.push("say", core.tell_him_text(said, note), said=said, note=core.voice(note))
            if wake:
                try:
                    self.push("wake", await asyncio.to_thread(core.wake_text, self.root, wake),
                              reasons=[core.voice(r) for r in wake.get("reasons") or []])
                except Exception as exc:
                    print(f"[simslink] wake failed: {exc!r}", flush=True)
        deadline = time.monotonic() + sync["wait"]
        while True:
            self.signal.clear()
            self.commands = core.prune_commands(self.commands)
            commands = core.pending_commands(self.commands, sync["after"])
            left = deadline - time.monotonic()
            if commands or left <= 0:
                break
            try:
                await asyncio.wait_for(self.signal.wait(), timeout=left)
            except asyncio.TimeoutError:
                pass
        return 200, {"ok": True, "commands": commands}

    async def photo(self, by: str, caption: str, shot: str, hold: str, data: bytes) -> tuple[int, dict]:
        try:
            query = core.clean_photo_query(by, caption, shot, hold)
            jpeg = await asyncio.to_thread(core.shrink_photo, data)
        except ValueError as exc:
            return 400, {"detail": str(exc)}
        name = await asyncio.to_thread(self.save_photo, jpeg)
        if query["by"] == "him":            # AI 说「拍一张」，转发程序替 TA 按的截图键
            if query["shot"]:
                self.shots[query["shot"]] = name
                for old in sorted(self.shots)[:-8]:
                    self.shots.pop(old, None)
            return 200, {"ok": True, "posted": 1}
        self.held.append(name)              # 玩家自己拍的（ta pic，或者开了自动分享）
        del self.held[:-core.HER_BATCH_MAX]
        if query["hold"]:
            return 200, {"ok": True, "posted": 0, "held": len(self.held)}
        names, self.held = self.held, []
        self.unseen_photos = (self.unseen_photos + names)[-core.HER_BATCH_MAX:]
        await asyncio.to_thread(core.record, self.root, {"events": [{"t": "photo", "by": "her", "count": len(names)}]})
        if self.cfg.webhook_url:
            note = await asyncio.to_thread(core.note_for_him, self.root)
            self.push("photo", core.photo_text(len(names), query["caption"], note), caption=query["caption"],
                      note=core.voice(note), images=[self.photo_url(n) for n in names])
        return 200, {"ok": True, "posted": len(names)}

    # ---- AI 这头 ----
    async def look(self) -> tuple[bool, str, list[str]]:
        """(连没连着, 现在的样子, 玩家发来还没看过的截图文件名)。"""
        live = await asyncio.to_thread(core.is_live, self.root)
        # 没接推送的（只靠工具来看）：她在游戏里说的话要在这里提一句；接了推送的已经推过了
        head = "" if self.cfg.webhook_url else await asyncio.to_thread(core.unseen_head, self.root)
        text = await asyncio.to_thread(core.format_now, self.root)
        photos, self.unseen_photos = self.unseen_photos, []
        if photos:
            head = (head + "\n" if head else "") + f"〔她从游戏里发来 {len(photos)} 张截图，你还没看过〕"
        return live, core.voice(f"{head}\n\n{text}" if head else text), photos

    async def do(self, body: dict) -> dict:
        """交一件事给游戏，等它做完回话。回 {ok, text[, photo]}；指令本身不对就 ValueError。"""
        command = core.clean_command(body)
        op = command["op"]
        if not await asyncio.to_thread(core.is_live, self.root):
            return {"ok": False, "text": core.voice("游戏没连着：她得开着小转发程序（SimsLinkBridge）并且进了游戏。")}
        blocked = await asyncio.to_thread(core.blocked_reason, self.root, op)
        if blocked:
            return {"ok": False, "text": core.voice(blocked)}
        cid = self.queue(op, command["args"])
        waiter = asyncio.get_running_loop().create_future()
        self.waiters[cid] = waiter
        try:
            result = await asyncio.wait_for(waiter, timeout=core.PHOTO_WAIT if op == "photo" else 15)
        except asyncio.TimeoutError:
            self.waiters.pop(cid, None)
            if op == "photo":
                text = "等了半分钟没等到照片：她电脑上的转发程序可能没开着，或者网慢。先别重拍，问她一声。"
            elif op == "say" and await asyncio.to_thread(core.screen, self.root) != "live":
                text = "她不在游戏世界里（捏人或读盘），这句话游戏没确认收到，可能等她回来才弹出来。别重发，等她回到游戏里再说。"
            else:
                text = "游戏 15 秒没回话（可能在读盘）。过一会儿 look 看看这件事排上没有，别急着重发。"
            return {"ok": False, "text": core.voice(text)}
        ok = bool(result.get("ok"))
        if ok and op == "say":
            await asyncio.to_thread(core.log_events, self.root, [{"t": "he", "text": command["args"]["text"][:300]}])
        reply = {"ok": ok, "text": core.voice(str(result.get("text") or "")[:9000])}
        if op == "photo":
            name = self.shots.pop(cid, None)
            if ok and name:
                reply["photo"] = name
                await asyncio.to_thread(core.log_events, self.root, [{"t": "photo", "by": "him"}])
            elif ok:
                reply = {"ok": False, "text": core.voice("游戏说拍了，但照片没传到服务器。让她看看黑窗口里写了什么。")}
        return reply

    async def reply(self, text: str) -> dict:
        """AI 在聊天里回的一句话交到这里：摘掉 ⟪小人:…⟫ 记号交给游戏去做，剩下的字弹进游戏。
        回摘干净的正文——给玩家看的应该是这一份。"""
        clean, marks = core.take_marks(text)
        if marks:
            await self._run_marks(marks)
        pieces = await asyncio.to_thread(core.mirror_pieces, self.root, clean)
        for piece in pieces:
            self.queue("say", {"text": piece})
        if pieces:
            await asyncio.to_thread(core.log_events, self.root, [{"t": "he", "text": clean[:300]}])
        return {"ok": True, "text": clean, "marks": len(marks), "shown": len(pieces)}

    async def _run_marks(self, marks: list[dict]) -> None:
        for cid in [c for c, m in self.marks.items() if time.time() - m["at"] > 120]:
            self.marks.pop(cid, None)           # 游戏一直没回话的旧账
        why = ""
        if not await asyncio.to_thread(core.is_live, self.root):
            why = "游戏没连着，没排上"
        else:
            why = await asyncio.to_thread(core.blocked_reason, self.root, "do")
        if why:
            await asyncio.to_thread(core.log_events, self.root,
                                    [{"t": "did", "ok": False, "label": m["label"], "text": why} for m in marks])
            return
        for mark in marks:
            self._queue_mark(mark)

    def _queue_mark(self, mark: dict) -> None:
        cid = self.queue(mark["op"], mark["args"])
        self.marks[cid] = dict(mark, at=time.time())

    async def _mark_done(self, mark: dict, result: dict) -> None:
        try:
            if core.mark_needs_retry(result) and not mark.get("retried"):
                await asyncio.sleep(3.5)        # 游戏那头去查这个中文名了，等它查完再排一次
                self._queue_mark(dict(mark, retried=True))
                return
            said = str(result.get("text") or "")[:200]
            if core.mark_needs_retry(result):   # 试了两次还是认不出这个名字
                said = "没排上：这里没有这个名字的动作（或者名字还没查到）。用 sims 工具 action=list 看看这个目标能做什么。"
            await asyncio.to_thread(core.log_events, self.root, [{
                "t": "did", "ok": bool(result.get("ok")), "label": mark["label"], "text": said}])
        except Exception as exc:
            print(f"[simslink] mark result failed: {exc!r}", flush=True)


# ───────────────────────── MCP：一个工具 ─────────────────────────

ACTIONS = ("look", "say", "objects", "list", "do", "cancel", "speed", "photo", "outfit", "money", "moodlets")


def tool_description(cfg: Config) -> str:
    talk = ("她开着游戏的时候，你在聊天里回的每一句都会自动弹在她游戏右上角，不用为了回话调 say。"
            "想让你的小人做事，最省事的是直接在回话里写记号：⟪小人:亲吻 → 小椴⟫（动作 → 目标，不写目标就是对自己）、"
            "⟪小人:穿 睡衣⟫、⟪小人:取消⟫，记号她看不到。"
            if cfg.reply_mirror else
            "她全屏玩的时候多半看不到聊天窗口：想让她在游戏里看到你的话 → action=say（弹在她屏幕右上角，头像是你的小人）。")
    return core.voice(
        "她在玩《模拟人生 4》的时候，你也在游戏里：看得见小人们在干嘛，能在她游戏里说话，能操控你自己的那个小人。"
        "第一次用先读说明书（ta-manual.md）。"
        "想知道现在什么样 → action=look（地点、时间、每个小人在干嘛、心情、需求、你和她的关系、最近发生了什么，"
        "还有她在游戏里对你说了什么）。" + talk +
        "想让她当场打字回你 → action=say 加 reply=true（弹一个输入框）。"
        "操控小人：action=objects 看这块地上有什么 → action=list target=谁或什么 看能做什么 → action=do target=… name=动作名。"
        "动作是排队的，可以连着 do 好几个；排错了 action=cancel。"
        "action=outfit 换衣服（不带 name 先看有哪几类）。action=money amount=数 给她打钱（进家里的存款）。"
        "action=moodlets 看小人身上每个情绪状态的完整说明。action=photo 拍一张游戏此刻的画面（会把图给你）。"
        "action=speed 改游戏速度，她在玩的时候别乱暂停。")


def build_mcp(hub: Hub) -> MCPServer:
    server = MCPServer(
        "SimsLink", version=VERSION,
        instructions=core.voice("让你住进她的 Sims 4 存档：看、在游戏里说话、操控你自己的小人。只有一个工具：sims。"))

    @server.tool(name="sims", description=tool_description(hub.cfg))
    async def sims(
        action: Annotated[Literal[ACTIONS], Field(description="look=现在什么样 + 最近发生了什么；say=在她游戏里说话；objects=这块地上有什么；list=对某个目标能做什么；do=去做；cancel=清空你小人手上和排队的事；outfit=换衣服；money=给她打钱；moodlets=情绪状态的完整卡片；photo=拍一张；speed=改游戏速度")],
        text: Annotated[str, Field(description="say：要说的话，像发消息一样，别太长。photo / money：附的一句话，可以不写")] = "",
        target: Annotated[str, Field(description="list / do：对谁或对什么。小人的名字、self（对自己）、phone（手机）、objects 里 # 后面的编号、或物件名字的一部分（取离你最近的，比如 Bed、Fridge）")] = "",
        name: Annotated[str, Field(description="do：list 里列出的动作名，照抄；只写一部分也行，对得上唯一一个就做。outfit：日常 / 正装 / 运动 / 睡衣 / 派对 / 泳装 / 热天 / 冷天 / 不穿，同一类有好几套就写「日常 2」")] = "",
        filter: Annotated[str, Field(description="list / objects：只看名字里带这几个字的（内部英文名和中文名都认：kiss、romance、cook、亲、抱）")] = "",
        who: Annotated[str, Field(description="一般不填＝你自己的小人。想指挥家里别的小人才写名字")] = "",
        reply: Annotated[bool, Field(description="say：true=弹一个输入框让她当场打字回你")] = False,
        amount: Annotated[int, Field(description="money：打多少，1 到 50000")] = 0,
        speed: Annotated[str, Field(description="speed：pause / 1 / 2 / 3")] = "",
    ):
        if action == "look":
            _live, now, photos = await hub.look()
            if not photos:
                return now
            return [now] + [Image(path=hub.photo_dir / n) for n in photos if (hub.photo_dir / n).exists()]
        try:
            result = await hub.do({"op": action, "args": {
                "who": who, "target": target, "name": name, "filter": filter, "text": text,
                "reply": reply, "speed": speed, "amount": amount}})
        except ValueError as exc:
            return f"没成：{exc}"
        said = result["text"] if result["ok"] else f"没成：{result['text']}"
        if result.get("photo") and (hub.photo_dir / result["photo"]).exists():
            return [said, Image(path=hub.photo_dir / result["photo"])]
        return said

    return server


class McpGate:
    """MCP 那扇门的锁：/mcp 要带 Bearer 钥匙；/mcp/<钥匙> 是给只能填一个地址的连接器用的。"""

    def __init__(self, app, token: str) -> None:
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("/mcp/"):
                if not _same(path[5:].strip("/"), self.token):
                    return await self._deny(send)
                scope = dict(scope, path="/mcp", raw_path=b"/mcp")
            elif path == "/mcp":
                headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
                if not _same(_bearer(headers), self.token):
                    return await self._deny(send)
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send) -> None:
        body = b'{"detail":"unauthorized"}'
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


# ───────────────────────── 拼起来 ─────────────────────────

def create_app(cfg: Config | None = None):
    cfg = cfg or Config()
    core.SETTINGS.pronoun = cfg.pronoun
    core.SETTINGS.mirror = cfg.reply_mirror
    hub = Hub(cfg)

    def allowed(request: Request, who: str) -> bool:
        given = _bearer(request.headers)
        return _same(given, cfg.ai_token) or (who == "mod" and _same(given, cfg.mod_token))

    denied = JSONResponse({"detail": "unauthorized"}, status_code=401)

    async def health(_request: Request):
        return JSONResponse({"ok": True, "version": VERSION, "live": await asyncio.to_thread(core.is_live, hub.root)})

    async def mod_sync(request: Request):
        if not allowed(request, "mod"):
            return denied
        status, body = await hub.sync(await request.body())
        return JSONResponse(body, status_code=status)

    async def mod_photo(request: Request):
        if not allowed(request, "mod"):
            return denied
        q = request.query_params
        status, body = await hub.photo(q.get("by", ""), q.get("caption", ""), q.get("shot", ""), q.get("hold", ""),
                                       await request.body())
        return JSONResponse(body, status_code=status)

    async def now(request: Request):
        if not allowed(request, "ai"):
            return denied
        live, text, photos = await hub.look()
        return JSONResponse({"ok": True, "live": live, "text": text,
                             "hint": core.voice(await asyncio.to_thread(core.playing_hint, hub.root)),
                             "images": [hub.photo_url(n) for n in photos]})

    async def do(request: Request):
        if not allowed(request, "ai"):
            return denied
        try:
            result = await hub.do(await request.json())
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        if result.get("photo"):
            result["image"] = hub.photo_url(result.pop("photo"))
        return JSONResponse(result)

    async def reply(request: Request):
        if not allowed(request, "ai"):
            return denied
        try:
            text = str((await request.json()).get("text") or "")
        except Exception:
            return JSONResponse({"detail": "bad json"}, status_code=400)
        return JSONResponse(await hub.reply(text))

    async def photo_file(request: Request):
        name = request.path_params["name"]
        path = hub.photo_dir / name
        if not _PHOTO_NAME.match(name) or not path.is_file():
            return JSONResponse({"detail": "not found"}, status_code=404)
        return FileResponse(path, media_type="image/jpeg")

    server = build_mcp(hub)
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True, host=cfg.host,
        # 这是放在公网上、靠钥匙守门的服务，不是只给本机用的：不按 Host 头拦
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    routes = [
        Route("/health", health),
        Route("/sims/mod/sync", mod_sync, methods=["POST"]),
        Route("/sims/mod/photo", mod_photo, methods=["POST"]),
        Route("/sims/now", now),
        Route("/sims/do", do, methods=["POST"]),
        Route("/sims/reply", reply, methods=["POST"]),
        Route("/photos/{name}", photo_file),
        *mcp_app.routes,
    ]
    app = Starlette(routes=routes, lifespan=lambda _app: server.session_manager.run())
    app.state.hub = hub
    gate = McpGate(app, cfg.ai_token)
    gate.hub = hub          # 测试用
    return gate
