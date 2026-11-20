"""配置：全部从环境变量来（也认当前文件夹里的 .env）。两把钥匙没给就自己生成、存在数据文件夹里。"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Config:
    def __init__(self) -> None:
        _load_dotenv(Path(".env"))
        env = os.environ.get
        self.data = Path(env("SIMSLINK_DATA", "data")).resolve()
        self.host = env("SIMSLINK_HOST", "0.0.0.0")
        self.port = int(env("SIMSLINK_PORT", "8787"))
        # 这台服务器对外的地址（https://sims.example.com）。截图的链接、印给你抄的配置都用它
        self.public_url = env("SIMSLINK_PUBLIC_URL", "").rstrip("/")
        # 游戏里出了事 / 玩家在游戏里说话，往哪儿推。不填就不推，AI 只能自己来看
        self.webhook_url = env("SIMSLINK_WEBHOOK_URL", "").strip()
        self.webhook_token = env("SIMSLINK_WEBHOOK_TOKEN", "").strip()
        # 你把 AI 的每句回话都交给 /sims/reply 了吗？交了就填 1：提示语会告诉 AI「照常回话就行」
        self.reply_mirror = env("SIMSLINK_REPLY_MIRROR", "").strip().lower() in ("1", "true", "yes", "on")
        # 给 AI 看的字里怎么称呼玩家
        self.pronoun = env("SIMSLINK_PLAYER_PRONOUN", "她").strip() or "她"
        self.mod_token = env("SIMSLINK_MOD_TOKEN", "").strip()
        self.ai_token = env("SIMSLINK_AI_TOKEN", "").strip()
        self._fill_tokens()

    def _fill_tokens(self) -> None:
        """没在环境变量里给钥匙：用数据文件夹里存着的；也没有就生成一对存下来。"""
        if self.mod_token and self.ai_token:
            return
        path = self.data / "tokens.json"
        saved: dict = {}
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        self.mod_token = self.mod_token or saved.get("mod_token") or secrets.token_urlsafe(24)
        self.ai_token = self.ai_token or saved.get("ai_token") or secrets.token_urlsafe(24)
        self.data.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mod_token": self.mod_token, "ai_token": self.ai_token}, indent=1), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def base(self) -> str:
        return self.public_url or f"http://你的服务器地址:{self.port}"

    def info(self) -> str:
        """印给装的人照抄的那几段。"""
        base = self.base()
        return "\n".join([
            "── 填进玩家电脑上的 SimsLinkBridge.cfg ──",
            json.dumps({"server": base, "token": self.mod_token}, ensure_ascii=False, indent=1),
            "",
            "── AI 这头 ──",
            f"MCP 连接器地址（地址里带着钥匙，别发给别人）：{base}/mcp/{self.ai_token}",
            f"或者 MCP 地址 {base}/mcp，请求头 Authorization: Bearer {self.ai_token}",
            f"直接调接口（GET /sims/now、POST /sims/do、POST /sims/reply）也用这把：Bearer {self.ai_token}",
            "",
            "── 现在的设置 ──",
            f"推送地址 SIMSLINK_WEBHOOK_URL：{self.webhook_url or '没填（游戏叫不醒 AI，AI 自己来看）'}",
            f"回话自动弹进游戏 SIMSLINK_REPLY_MIRROR：{'开' if self.reply_mirror else '关'}",
            f"怎么称呼玩家 SIMSLINK_PLAYER_PRONOUN：{self.pronoun}",
            f"数据文件夹：{self.data}",
        ])
