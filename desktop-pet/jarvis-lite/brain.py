import base64
import json
import os
import time
from datetime import datetime

import requests

import config
import activity


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

    def _memo_lines(self):
        return [ln.strip() for ln in (self.user_memo or "").splitlines()
                if ln.strip().startswith("-")]

    def memo_block(self):
        if not self.user_memo:
            return ""
        return "\n\n【你记得的关于他的事（长期记忆，自然用上，不要生硬复述）】\n" + self.user_memo

    def learn_about_user(self, user_text, reply):
        """从一轮对话里提炼「关于用户的长期事实」并合并进记忆。

        返回新增条数。失败不抛异常（记忆是加分项，不该影响聊天）。
        """
        user_text = (user_text or "").strip()
        reply = (reply or "").strip()
        if len(user_text) < 4 or not reply:
            return 0
        ask = (
            "下面是你和用户的一段对话。请提取「关于用户这个人值得长期记住的事实」，"
            "每条一行、以「- 」开头，要具体（喜好、习惯、正在做什么、在意什么、反感什么、"
            "说话风格偏好）。只写有长期价值的事实，不要写这次对话的临时内容，"
            "也不要重复【已有记忆】里已经有的。没有新东西就只回复「无」。\n\n"
            "【已有记忆】\n%s\n\n【这次对话】\n用户：%s\n你：%s\n"
            % (self.user_memo or "(空)", user_text[:600], reply[:600])
        )
        try:
            out = self.once(ask, record=False, fresh=True, kind="memo")
        except Exception:
            return 0
        if not out or "无" in out[:6] or out.startswith("[ERROR]"):
            return 0
        old = self._memo_lines()
        old_key = [self._norm(x) for x in old]
        added = []
        for ln in out.splitlines():
            ln = ln.strip()
            if not ln.startswith("-"):
                continue
            ln = "- " + ln.lstrip("-").strip()
            body = self._norm(ln)
            if len(body) < 4:
                continue
            # 和已有条目太像就不加，避免同一个事实反复堆
            if any(self._overlap(body, k) >= 0.5 for k in old_key):
                continue
            added.append(ln)
        if not added:
            return 0
        merged = old + added
        merged = merged[-self.MAX_MEMO_LINES:]
        self.save_memo("\n".join(merged))
        return len(added)

    @staticmethod
    def _norm(s):
        return "".join(ch for ch in s if ch.strip() and ch not in "-：:，,。.、！!？?")

    @staticmethod
    def _overlap(a, b):
        g = {a[i:i + 2] for i in range(max(0, len(a) - 1))}
        h = {b[i:i + 2] for i in range(max(0, len(b) - 1))}
        if not g or not h:
            return 0.0
        return len(g & h) / float(len(g | h))

    MAX_MEMO_LINES = 40

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

    def _save_history(self):
        with open(self._today_file(), "w", encoding="utf-8") as f:
            json.dump(self.history[-60:], f, ensure_ascii=False, indent=2)

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
                    if x1 - x0 > 120 and y1 - y0 > 90:
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
