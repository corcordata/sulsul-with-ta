# 安装说明

一共三样东西，装在三个地方：

| 是什么 | 装在哪 | 谁来装 |
|---|---|---|
| **mod**（`SulSul.ts4script`） | 你玩 Sims 4 的那台电脑（Windows 或 Mac），游戏的 Mods 文件夹 | 你 |
| **小转发程序**（`SulSulBridge`） | 同一台电脑，放哪都行 | 你 |
| **服务器小服务** | 你自己的服务器（你家小机住的那台，或任何一台外网能访问的机器） | 你，或者交给你家会写代码的小机 |

顺序：先装服务器（它会给你两把钥匙），再装电脑上那两样。下载的时候按你的电脑选 `windows` 或 `mac` 那个压缩包，里面 mod 和服务器是一样的，只有小转发程序不同。

> 为什么要多一个「小转发程序」：Sims 4 自带的 Python 不能上 https，mod 只能跟本机说话，所以由它替 mod 把话带到你的服务器。

---

## 第一步：服务器

需要 Python 3.10 或更新，或者 Docker。压缩包里的 `3-server` 文件夹（仓库里是 `server/`）整个传到服务器上。

**用 Python：**

```bash
cd 3-server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # 然后按下面的说明改 .env
.venv/bin/python -m sulsul_server
```

**用 Docker：**

```bash
cd 3-server
cp .env.example .env        # 然后按下面的说明改 .env
docker compose up -d --build
```

**`.env` 里要填的：**

| 这一行 | 填什么 |
|---|---|
| `SULSUL_PUBLIC_URL` | 这个服务对外的地址，比如 `https://sims.你的域名.com`。**必填** |
| `SULSUL_WEBHOOK_URL` | 游戏里有事时往哪推（见第四步的接法 B）。只用 MCP 连接器就留空 |
| `SULSUL_WEBHOOK_TOKEN` | 推送时带的钥匙（可不填） |
| `SULSUL_REPLY_MIRROR` | 你把 TA 的每句回话都交给 `/sims/reply` 了就填 `1`，否则留空 |
| `SULSUL_PLAYER_PRONOUN` | 给 TA 看的字里怎么称呼你：`她`（默认）/ `他` / `TA` |
| `SULSUL_PORT` | 端口，默认 8787 |

**要有 https。** Claude 的连接器只认 https 地址，你电脑上的小转发程序也会带着钥匙连过来。最省事的办法是在前面放一个 Caddy 或 nginx，把你的域名转到 `127.0.0.1:8787`。

开起来以后，印出钥匙和要抄的配置：

```bash
.venv/bin/python -m sulsul_server info
# Docker：docker compose exec sulsul python -m sulsul_server info
```

它会印出两段：一段填进电脑上的 `SulSulBridge.cfg`，一段是给 TA 用的 MCP 地址。**这两段里都有钥匙，别发到公开的地方。**

想让它开机自启，用 systemd、pm2、或者 Docker 的 `restart: unless-stopped`（compose 文件里已经写了）。

---

## 第二步：电脑上的 mod

1. 把 `1-put-into-Mods` 里的 `SulSul` 文件夹整个拷到：
   `文档 \ Electronic Arts \ The Sims 4 \ Mods`（Mac：`文稿 / Electronic Arts / The Sims 4 / Mods`）
   拷完是 `Mods \ SulSul \ SulSul.ts4script`。**不要再多套一层文件夹**，脚本 mod 放深了游戏不认。
2. 游戏里：游戏选项 → 其他 → 勾上「启用自定义内容和模组」和「允许脚本模组」，重启游戏。
3. 你的存档里要有 TA 的小人，跟你的小人住同一户。没有就先捏一个。

## 第三步：电脑上的小转发程序

### Windows

1. 把 `2-bridge` 文件夹放到桌面（放哪都行，里面两个文件要在一起）。
2. 用记事本打开 `SulSulBridge.cfg`，把第一步 `info` 印出来的那段贴进去，保存：
   ```json
   {
    "server": "https://sims.你的域名.com",
    "token": "服务器给的 MOD 钥匙"
   }
   ```
3. 双击 `SulSulBridge.exe`。会开一个黑色小窗口，写着「服务器连得上 ✓」。
   第一次打开 Windows 可能弹蓝色的「Windows 已保护你的电脑」：点「更多信息」→「仍要运行」。（程序没有花钱买签名，所以会有这一下。不放心可以自己从源码编，见 README。）

### Mac

Mac 版能做的：看、说话、操控小人、换衣服、打钱、情绪卡片、中文名、发截图、游戏叫醒、回话弹进游戏。
**Mac 版没有的**：F9 / F10 快捷键。跟 TA 说话用游戏里的输入条：`Cmd + Shift + C`，输入 `ta` 回车，会弹出输入框，同时自动切到中文输入法，关掉切回你原来用的那个。

1. 把 `2-bridge` 文件夹放到桌面。
2. 用「文本编辑」打开 `SulSulBridge.cfg`，把第一步 `info` 印出来的那段贴进去，保存。
3. 打开「终端」（在启动台里搜「终端」），输入 `sh`，按一下空格，把 `start.command` 这个文件拖进终端窗口，回车。看到「服务器连得上 ✓」就对了。
   直接双击会被 macOS 拦下来，因为这个程序没有花钱买苹果的签名。
4. TA 第一次拍照时，macOS 会问两次权限：允许「终端」控制 System Events；在 系统设置 → 隐私与安全性 → 辅助功能 里把「终端」勾上。不给也行，只是 TA 拍不了照。

Mac 上打开游戏输入条的键是 `Cmd + Shift + C`，下面写 `Ctrl + Shift + C` 的地方都换成它。

### 两边都一样的

**每次玩之前**：先开小转发程序，再开游戏进存档。黑窗口（Mac 是终端窗口）里出现「游戏连上了 ✓」就是通了。玩的时候这个窗口一直开着，最小化就行。

**第一次进存档**，右上角会提醒你告诉它哪个小人是谁。按 `Ctrl + Shift + C` 打开左上角的输入条，输入：

```
ta who
```

它会把家里的小人编上号列出来，然后按编号选（这个输入条里常常打不了中文，所以用编号）：

```
ta ta 1        ← 1 号是 TA
ta me 2        ← 2 号是你
```

只用设一次。`ta status` 可以看连没连上、设的是谁。

---

## 第四步：接上你的 TA

两种接法，按你家小机的情况选。可以先接 A，以后再加 B。

### 接法 A：MCP 连接器（最简单）

适合：用 Claude App / Claude Code / 其他支持 MCP 的客户端，没有自己的消息程序。

把第一步 `info` 印出来的 MCP 地址加成连接器：

- **Claude App**：在设置里添加自定义连接器（Custom connector），地址填 `https://sims.你的域名.com/mcp/TA的钥匙`（钥匙在地址里，不用再填别的）
- **Claude Code / 能填请求头的客户端**：地址 `https://sims.你的域名.com/mcp`，请求头 `Authorization: Bearer TA的钥匙`

然后把 `TA-MANUAL.md` 的内容交给 TA（放进项目说明、系统提示或知识库）。

这种接法下：TA 能看、能在游戏里说话、能操控小人、换衣服、打钱、拍照。**但游戏叫不醒它**，你在游戏里说的话要等它下一次看的时候才看得到。所以玩的时候在聊天窗口叫它一声「看看游戏」。

### 接法 B：推送 + 回话入口（全功能）

适合：你家小机跑在自己的服务器上，有一个程序在收发消息。这一步要写一点代码，可以把这一节整段交给你家会写代码的小机。

**1. 收推送。** 在 `.env` 里填 `SULSUL_WEBHOOK_URL`。以下三种时候，小服务会往这个地址 POST 一段 JSON（填了 `SULSUL_WEBHOOK_TOKEN` 的话带 `Authorization: Bearer …`）：

```json
{ "kind": "say",   "text": "…", "said": "她打的那句", "note": "〔Sims 4〕注解", "at": 1790000000.0 }
{ "kind": "wake",  "text": "…", "reasons": ["小椴 开始 亲吻 → Tom（Tom 不是你）"], "at": … }
{ "kind": "photo", "text": "…", "caption": "…", "note": "…", "images": ["https://…/photos/xxx.jpg"], "at": … }
```

- `text` 是拼好的一整段，**最简单的做法是把它当成一条发给 TA 的消息**，让 TA 照常回话
- 想做得细一点：`say` 时把 `said` 当成她说的话显示在聊天里，`note` 只给 TA 看
- `wake` 是游戏自己来叫的（她没说话），不要显示成她说的话
- 收到后回 2xx 就行；回 5xx 或连不上会重试两次

**2. 把 TA 的回话交回来。** TA 每回一句话，在显示给她之前，先 POST 到 `/sims/reply`（带 `Authorization: Bearer TA的钥匙`）：

```json
POST /sims/reply   { "text": "来了。⟪小人:亲吻 → 小椴⟫" }
→ { "ok": true, "text": "来了。", "marks": 1, "shown": 1 }
```

它会把 `⟪小人:…⟫` 记号摘掉交给游戏去做，把正文弹进游戏右上角（游戏没开就什么都不做）。**显示给她的用返回的 `text`**（记号已经摘掉了）。做完这一步，把 `.env` 里的 `SULSUL_REPLY_MIRROR` 填成 `1` 并重启小服务：从此给 TA 的提示会写「照常回话就行」。

**3. 让 TA 能看和操控。** 二选一：接 MCP（同接法 A），或者把这两个接口包成你家自己的工具：

```
GET  /sims/now                         → { "live": true, "text": "现在什么样…", "hint": "…", "images": [] }
POST /sims/do   { "op": "say", "args": { "text": "…" } }   → { "ok": true, "text": "…" }
```

`op` 有：`say` `objects` `list` `do` `cancel` `outfit` `money` `moodlets` `photo` `speed`；`args` 里用到的有 `text` `target` `name` `filter` `who` `reply` `amount` `speed`，意思见 `TA-MANUAL.md`。`photo` 成功时多回一个 `image`（图片地址）。

**4.** 把 `TA-MANUAL.md` 交给 TA。

---

## 不对劲的时候

| 看到什么 | 多半是 |
|---|---|
| 黑窗口：「服务器不认这把钥匙」 | `SulSulBridge.cfg` 里的 `token` 要填 MOD 那把，不是 TA 那把 |
| 黑窗口：「现在连不上服务器」 | 地址写错、服务没开、或者没有 https |
| 黑窗口一直停在「等游戏来敲门」 | mod 没装对（多套了一层文件夹 / 没勾「允许脚本模组」），或者还没进存档 |
| 游戏里 `ta status` 说「没连上小转发程序」 | 黑窗口没开 |
| TA 说「没找到你的小人」 | 还没设：`ta who`，再 `ta ta 编号` |
| 动作名是英文 | 那个动作是别的 mod 加的、且没有中文字库；游戏自己的动作应该是中文 |
| 按 F9 没反应 | 笔记本要按 `Fn + F9`；或者这个键被别的程序占了，黑窗口里会写，用 `ta key F8` 换一个。Mac 版没有快捷键 |
| TA 拍照说「游戏没存出新截图」 | 输入法在中文状态、正在打字、或开着菜单时截图键不灵，等一下再拍 |

要找人帮忙看，带上这三样：黑窗口的截图、`Mods \ SulSul \ SulSul.log`、`文档 \ Electronic Arts \ The Sims 4 \ lastException.txt`（有的话）。**截图前把黑窗口里的地址遮一下。**

## 卸载

把 `Mods` 里的 `SulSul` 文件夹删掉，把小转发程序的文件夹删掉，服务器上把小服务停掉。别的什么都不会留下，存档不受影响。
