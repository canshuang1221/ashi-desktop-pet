import base64
import json
import os
import time
from datetime import datetime

import requests

import config


class Brain:
    """OpenAI 兼容接口客户端，含视觉能力与本地记忆。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.history = []
        self._load_history()

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
        msgs = [{"role": "system", "content": self.cfg["persona"]}]
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
        try:
            r = requests.post(self._endpoint(), headers=self._headers(), json=body, stream=True, timeout=90)
        except Exception as e:
            yield "[ERROR]连不上接口：" + str(e)
            return
        if r.status_code != 200:
            # 免费 API 常有并发/速率限制，退避重试而不是直接报错
            if r.status_code == 429 and _retry < 2:
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
            yield "[ERROR]接口没有返回内容。可能原因：该接口不支持流式输出或不支持图片输入（模型 %s）。" % model
            return

        if full and record:
            now = datetime.now().strftime("%H:%M:%S")
            self.history.append({"role": "user", "kind": kind,
                                 "content": user_text or "(看了屏幕)", "ts": now})
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


def grab_screen(scale=0.6, quality=72, as_jpeg=True, foreground=True):
    """截屏返回 base64。默认优先截「前台窗口」而不是全屏：
    全屏压到一半分辨率时，小字全糊，模型只能看出大布局，说话自然没代入感；
    聚焦当前窗口后画面内容密度高得多，同样的字节数能看清他在用什么、干什么。

    前台窗口不在主屏/取不到时自动退回全屏。
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
