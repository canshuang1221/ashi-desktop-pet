import base64
import json
import os
import time
from datetime import datetime

import requests

import config
import activity


# 前台窗口区域至少要占整屏这么多，才认为"这是个值得看的窗口"。
# 弹出菜单/小控件也会成为前台窗口：菜单约 1.7%、普通窗口约 23%，取 12% 能
# 干净地分开两者。见 foreground_crop_ok()。
FOREGROUND_MIN_RATIO = 0.12


def _short_user(kind, text):
    """记忆里不要存自动触发的长提示词。

    感知提示词约 500 字，绝大部分是固定模板 + 「最近说过的话」列表。
    存进历史后每条都要占上下文（_build 会带最近 12 条），既费 token
    又会让模型把指令当成用户说过的话。真正有价值的是它自己的回复，
    所以自动触发的只留一个短标记。
    """
    if kind == "chat":
        return text or "(空)"
    if kind == "auto":
        return "(自动看了屏幕)"
    return "(%s)" % kind


class Brain:
    """OpenAI 兼容接口客户端，含视觉能力与本地记忆。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.history = []
        self._load_history()
        self.user_memo = self._load_memo()

    # ---------- 关于用户的长期记忆 ----------
    # 和「对话记录」不是一回事：对话记录是流水账（按天、只留最近 60 条），
    # 这里是**提炼过的事实**（他喜欢什么、在做什么、反感什么），
    # 会一直拼在 system 里，所以它越用越懂他。
    #
    # 沉淀时机：**不是每聊一轮就提炼**。早先那样做，每轮对话都可能往档案里
    # 塞几条，聊得越多、档案越臃肿，而且大半是「今天聊了某个话题」这种
    # 一次性内容。现在改成**每天首次启动时**，把上一天之后的素材一次性沉淀：
    # 素材有两路 —— memory/YYYY-MM-DD.json（真聊过的）和
    # activity/history.md（从屏幕看到的），后者保证他一句话不说也有得沉淀。
    # 关键是**整体重写**而不是追加：模型看着旧档案 + 新素材输出一份新的，
    # 天然去重、能删过时内容，所以档案不会无限膨胀。
    def _load_memo(self):
        try:
            with open(config.USER_MEMO_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def save_memo(self, text):
        self.user_memo = (text or "").strip()
        try:
            with open(config.USER_MEMO_PATH, "w", encoding="utf-8") as f:
                f.write(self.user_memo + "\n")
        except Exception:
            pass

    def clear_user_memo(self):
        self.save_memo("")

    def memo_block(self):
        if not self.user_memo:
            return ""
        return "\n\n【你记得的关于他的事（长期记忆，自然用上，不要生硬复述）】\n" + self.user_memo

    def user_block(self):
        """称呼 + 替他出头那段。

        刻意**不写进 persona**：persona 是可编辑的（设置里能改，且程序退出时
        会把内存里的配置写回 config.json），一旦用户改过或某次写回带回了旧文案，
        写在提示词里的改动就悄悄丢了 —— 这个坑已经踩过一次。
        这段由代码按当前配置现生成，改不掉也丢不掉。
        """
        name = ((self.cfg.get("pet") or {}).get("user_name") or "").strip()
        if not name:
            return ""
        return ("\n\n【怎么称呼他、怎么替他出头】\n"
                "叫他「%s」。你不是站在旁边看的第三者：他不爽你先替他吐槽，"
                "他碰上离谱的需求你替他喊冤，他干累了就替他说出来 —— 用你的话替他说，"
                "但别点评他、别给建议、别问他怎么了。" % name)

    # ---------- 每日沉淀 ----------
    # 进度标记：memory/.last_digest 里存着「已经沉淀到哪一天」。
    # 只要它落后于今天，就说明有没沉淀的日子（断档也能补上）。
    def _read_mark(self):
        try:
            with open(config.DIGEST_MARK, encoding="utf-8") as f:
                return f.read().strip()[:10]
        except Exception:
            return ""

    def _write_mark(self, day):
        try:
            os.makedirs(config.MEMORY_DIR, exist_ok=True)
            with open(config.DIGEST_MARK, "w", encoding="utf-8") as f:
                f.write((day or "") + "\n")
        except Exception:
            pass

    @staticmethod
    def _is_day(s):
        return (len(s) == 10 and s[4] == "-" and s[7] == "-"
                and s[:4].isdigit() and s[5:7].isdigit() and s[8:].isdigit())

    def pending_digest_days(self):
        """还没沉淀进长期记忆的日期（升序）。

        来源是两处的并集：memory/ 里的对话流水（真聊过的）和
        activity/ 档案里的日期（从屏幕看到的）。取并集是为了让
        「只开了屏幕、一句话没说」的日子也能被沉淀进去。

        不含今天：今天的对话留到明天才沉淀，避免边聊边改档案。
        """
        last = self._read_mark()
        today = datetime.now().strftime("%Y-%m-%d")
        days = set()
        try:
            for f in os.listdir(config.MEMORY_DIR):
                d = f[:-5] if f.endswith(".json") else ""
                if self._is_day(d):
                    days.add(d)
        except Exception:
            pass
        try:
            days |= set(activity.dates())
        except Exception:
            pass
        return sorted(d for d in days
                      if d < today and (not last or d > last))

    MAX_GATHER_DAYS = 7           # 每次沉淀最多回看几天，免得素材过长

    def _gather_material(self, days, max_chars=6000):
        """把指定几天的「看到的」和「聊过的」拼成给模型看的素材。

        两条来源各分一半预算：第一次沉淀时（积攒了很多天历史、还没有
        进度标记）活动那一段可能很长，如果让它先吃掉全部配额，聊天记录
        就被挤没了。所以各自截断。

        只取 kind=="chat" 的记录：自动感知/搭话那些（kind=auto）属于
        「活动」，已经由 activity 那一路覆盖了，再喂一遍是重复。
        """
        days = list(days)[-self.MAX_GATHER_DAYS:]
        half = max(800, max_chars // 2)

        try:
            acts = (activity.sections_for(days) or "")[:half]
        except Exception:
            acts = ""

        lines = []
        for d in days:
            path = os.path.join(config.MEMORY_DIR, d + ".json")
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for m in data:
                if m.get("kind") != "chat":
                    continue
                text = (m.get("content") or "").strip()
                if not text or text.startswith("[ERROR]"):
                    continue
                who = "他" if m.get("role") == "user" else "你"
                lines.append("%s（%s）：%s" % (who, d[5:], text[:200]))
        dlg = "\n".join(lines[-120:])[:half]

        parts = []
        if acts:
            parts.append("【这几天的活动（从屏幕看到的，不是他说的）】\n" + acts)
        if dlg:
            parts.append("【这几天你们聊过的】\n" + dlg)
        return "\n\n".join(parts)[:max_chars]

    DIGEST_PROMPT = (
        "你在维护一份「关于用户」的长期记忆档案。这份档案会一直放在你的系统提示里，"
        "所以越精简、越准，你就越懂他。\n\n"
        "下面是【当前档案】、【他这几天的活动】和【你们这几天的对话】。"
        "请输出**更新后的完整档案**，规则：\n"
        "① 每条一行、以「- 」开头；\n"
        "② 只留**长期不变**的事实——他的喜好、习惯、性格、在做的项目、"
        "在意什么、反感什么、说话风格偏好；\n"
        "③ 把新出现、值得长期记住的补进去；重复的合并成一条；"
        "已经被推翻或过时的删掉；\n"
        "④ 像「某天看了什么视频」「今天聊了某件事」这种临时内容，一律不要；\n"
        "⑤ 全篇**最多 25 条**，越精炼越好；\n"
        "⑥ 直接输出条目，不要标题、不要解释；\n"
        "⑦ 如果这几天没有值得长期记住的新内容，就原样保留【当前档案】里的条目。\n\n"
        "【当前档案】\n%s\n\n%s\n"
    )

    def digest_memory(self, days):
        """把指定几天的素材沉淀成一份「更新后的」长期记忆。

        返回写入的条数（0 = 没成功或没内容）。**整体重写**而不是追加——
        模型看着旧档案 + 新素材输出一份新档案，天然就去重、能删过时内容，
        这正是「不再越攒越臃肿」的关键。失败时不推进进度标记，下次会重试。
        """
        days = sorted(d for d in (days or []) if d)
        if not days:
            return 0
        material = self._gather_material(days)
        if not material.strip() and not self.user_memo:
            self._write_mark(days[-1])
            return 0
        ask = self.DIGEST_PROMPT % (self.user_memo or "(还是空的)",
                                    material or "（这几天没有新素材）")
        try:
            out = self.once(ask, record=False, fresh=True, kind="digest")
        except Exception:
            return 0
        if not out or out.startswith("[ERROR]"):
            return 0

        seen, merged = set(), []
        for ln in out.splitlines():
            ln = ln.strip()
            if not ln.startswith("-"):
                continue
            ln = "- " + ln.lstrip("-").strip()
            key = self._norm(ln)
            if len(key) < 4 or key in seen:
                continue
            seen.add(key)
            merged.append(ln)
        if not merged:
            return 0
        self.save_memo("\n".join(merged[:self.MAX_MEMO_LINES]))
        self._write_mark(days[-1])
        return len(merged)

    @staticmethod
    def _norm(s):
        return "".join(ch for ch in s if ch.strip() and ch not in "-：:，,。.、！!？?")

    MAX_MEMO_LINES = 30

    # ---------- 配置 ----------
    def reload(self, cfg):
        self.cfg = cfg

    @property
    def ready(self):
        return bool(self.cfg["api"]["api_key"].strip())

    def _endpoint(self):
        return self.cfg["api"]["base_url"].rstrip("/") + "/chat/completions"

    def _headers(self):
        return {
            "Authorization": "Bearer " + self.cfg["api"]["api_key"].strip(),
            "Content-Type": "application/json",
        }

    # ---------- 对话 ----------
    def _build(self, user_text, image_b64=None, fresh=False):
        # 长期记忆 + 今日足迹都拼在 system 里：不占历史窗口，也不会被 60 条上限滚掉
        msgs = [{"role": "system",
                 "content": config.render(self.cfg["persona"], self.cfg)
                 + self.user_block()
                 + self.memo_block() + activity.block()}]
        if not fresh:
            msgs += self.history[-12:]
        if image_b64:
            model = self.cfg["api"]["vision_model"] or self.cfg["api"]["model"]
            msgs.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_b64}},
                        {"type": "text", "text": user_text or "看看我的屏幕"},
                    ],
                }
            )
        else:
            model = self.cfg["api"]["model"]
            msgs.append({"role": "user", "content": user_text})
        return model, msgs

    def stream(self, user_text, image_b64=None, _retry=0, record=True,
               fresh=False, kind="chat"):
        """生成器：逐段产出回复文本。出错时产出 [ERROR]xxx。

        record=False 时不写入本地记忆（自动触发的感知/搭话用）。
        fresh=True 时不带历史上下文（点气泡打开的全新对话用）。
        kind: 记录来源标记（chat/look/note/auto），历史窗口按它过滤显示。
        """
        model, msgs = self._build(user_text, image_b64, fresh)
        body = {
            "model": model,
            "messages": msgs,
            "temperature": self.cfg["api"]["temperature"],
            "max_tokens": self.cfg["api"]["max_tokens"],
            "stream": True,
        }
        MAX_RETRY = 2
        try:
            r = requests.post(self._endpoint(), headers=self._headers(), json=body,
                              stream=True, timeout=(10, 90))
        except Exception as e:
            # 网络抖动/超时：退避后重试，别把一次偶发失败直接甩给用户
            if _retry < MAX_RETRY:
                time.sleep(1.5 * (_retry + 1))
                yield from self.stream(user_text, image_b64, _retry + 1,
                                       record, fresh, kind)
                return
            yield "[ERROR]连不上接口（已重试 %d 次）：%s" % (_retry, e)
            return
        if r.status_code != 200:
            # 429 限流 / 5xx 网关抖动：退避重试；4xx 参数错误重试也没用
            if (r.status_code == 429 or r.status_code >= 500) and _retry < MAX_RETRY:
                time.sleep(2 * (_retry + 1))
                yield from self.stream(user_text, image_b64, _retry + 1,
                                       record, fresh, kind)
                return
            yield "[ERROR]%s %s" % (r.status_code, r.text[:200])
            return

        full = ""
        saw_sse = False
        raw_lines = []
        for line in r.iter_lines():
            if not line:
                continue
            s = line.decode("utf-8", errors="replace").strip()
            raw_lines.append(s)
            if not s.startswith("data:"):
                continue
            saw_sse = True
            data = s[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content", "")
            except Exception:
                continue
            if delta:
                full += delta
                yield delta

        if not full:
            # 兼容不按 SSE 流式返回的接口（如部分本地/实验网关）：
            # 尝试把响应整体当 JSON 解析一次
            try:
                whole = json.loads("\n".join(raw_lines))
                full = (whole["choices"][0].get("message", {})
                        .get("content", "") or "")
            except Exception:
                full = ""
            if full:
                yield full

        if not full:
            # 流被中途掐断也会走到这里，先重试再报错
            if _retry < MAX_RETRY:
                time.sleep(1.5 * (_retry + 1))
                yield from self.stream(user_text, image_b64, _retry + 1,
                                       record, fresh, kind)
                return
            yield "[ERROR]接口没有返回内容。可能原因：该接口不支持流式输出或不支持图片输入（模型 %s）。" % model
            return

        if full and record:
            now = datetime.now().strftime("%H:%M:%S")
            self.history.append({"role": "user", "kind": kind,
                                 "content": _short_user(kind, user_text), "ts": now})
            self.history.append({"role": "assistant", "kind": kind,
                                 "content": full, "ts": now})
            self._save_history()

    def once(self, prompt, image_b64=None, record=True, fresh=False, kind="chat"):
        return "".join(self.stream(prompt, image_b64, record=record,
                                   fresh=fresh, kind=kind))

    # ---------- 记忆 ----------
    def _today_file(self):
        return os.path.join(config.MEMORY_DIR, datetime.now().strftime("%Y-%m-%d") + ".json")

    def _load_history(self):
        p = self._today_file()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    # 每天各留多少条。以前不区分，一律只留最后 60 条 —— 但自动感知每半分钟
    # 就写 2 条，60 条只够装 15 分钟，于是「真聊过的话」很快被感知流水挤出去
    # （实测：三天的日志里 kind=chat 一条都不剩）。而长期记忆的每日沉淀恰恰
    # 要读前一天真聊了什么，全被挤没就只剩「看了屏幕」可沉淀。所以分开留。
    KEEP_CHAT = 400     # 真聊过的（chat）+ 让整理笔记的（note）多留
    KEEP_AUTO = 60      # 感知流水只留最近一小段，够接上下文就行

    def _kept(self):
        """筛出要留的记录（保序）：真聊过的多留、感知流水少留。"""
        chat = [m for m in self.history if m.get("kind") in ("chat", "note")]
        auto = [m for m in self.history if m.get("kind") not in ("chat", "note")]
        keep = {id(m) for m in chat[-self.KEEP_CHAT:]}
        keep |= {id(m) for m in auto[-self.KEEP_AUTO:]}
        return [m for m in self.history if id(m) in keep]

    def _save_history(self):
        # 内存里也按同样规则收一下，免得长时间运行越攒越多
        self.history = self._kept()
        with open(self._today_file(), "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def note_reply(self, text, kind="auto", tag=""):
        """把「真正发出去的那句话」记进当天记忆。

        以前是在模型一返回就记（stream 的 record 分支），结果被拦掉的句子
        ——带问号、助手口气、劝休息的那些——也一并写进了历史。
        用户在「它都说了什么」里会看到它根本没说过的话。所以改成确认发出后再记。
        """
        text = (text or "").strip()
        if not text:
            return
        now = datetime.now().strftime("%H:%M:%S")
        content = ("[%s] %s" % (tag, text)) if tag else text
        self.history.append({"role": "user", "kind": kind,
                             "content": _short_user(kind, ""), "ts": now})
        self.history.append({"role": "assistant", "kind": kind,
                             "content": content, "ts": now})
        self._save_history()

    def clear_history(self):
        self.history = []
        self._save_history()

    # ---------- 笔记 ----------
    def save_note(self, title, text):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(config.NOTES_DIR, ts + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# %s\n\n> %s\n\n%s\n" % (title, datetime.now().strftime("%Y-%m-%d %H:%M"), text))
        return path


def foreground_crop_ok(w, h, screen_w, screen_h):
    """前台窗口区域够不够大 —— 够大才值得照它裁。

    弹出菜单、小控件也会成为「前台窗口」。照它裁的话整张图就缩成一小块菜单
    （实测出过 148×231 的小图，于是它只会聊菜单里那几行字，屏幕上真正的
    内容全丢了）。太小就宁可退回整屏。
    """
    if w <= 0 or h <= 0 or screen_w <= 0 or screen_h <= 0:
        return False
    return w * h >= FOREGROUND_MIN_RATIO * screen_w * screen_h


def grab_screen(scale=0.85, quality=82, as_jpeg=True, foreground=True):
    """截屏返回 base64。默认优先截「前台窗口」而不是全屏：
    全屏压到一半分辨率时，小字全糊，模型只能看出大布局，说话自然没代入感；
    聚焦当前窗口后画面内容密度高得多，同样的字节数能看清他在用什么、干什么。

    前台窗口不在主屏/取不到时自动退回全屏。

    注意 scale/quality 的取舍：实测 0.6 + quality 72 时，代码框里的小字会被
    模型读错（jarvis-lite 读成 jarvís-lite、docking 读成 dorking）。
    现在默认 0.85 + 82，文字可读性明显变好，代价是截图体积约翻倍。
    可在设置面板里调。scope="screen" 时绕过前台窗口裁剪，截整个屏幕。
    """
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtWidgets import QApplication

    screen = QApplication.instance().primaryScreen()
    img = screen.grabWindow(0).toImage()

    if foreground:
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                r = wintypes.RECT()
                if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    # 只裁主屏范围内有效的前台窗口区域（多屏/负坐标保护）
                    x0, y0 = max(0, r.left), max(0, r.top)
                    x1 = min(img.width(), r.right)
                    y1 = min(img.height(), r.bottom)
                    if foreground_crop_ok(x1 - x0, y1 - y0,
                                          img.width(), img.height()):
                        img = img.copy(x0, y0, x1 - x0, y1 - y0)
        except Exception:
            pass

    if scale < 1.0:
        img = img.scaled(
            int(img.width() * scale), int(img.height() * scale),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    if as_jpeg:
        img.save(buf, "JPG", quality)
        prefix = "data:image/jpeg;base64,"
    else:
        img.save(buf, "PNG")
        prefix = "data:image/png;base64,"
    buf.close()
    return prefix + base64.b64encode(bytes(ba)).decode("ascii")


def split_data_url(s):
    """兼容模型返回的裸 base64 或带前缀的 data url。"""
    return s.split(",", 1)[1] if s.startswith("data:") else s
