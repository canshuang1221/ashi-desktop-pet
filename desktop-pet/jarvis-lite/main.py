import ctypes
import os
import random
import sys
from collections import deque
from ctypes import wintypes
from datetime import datetime

from PySide6.QtCore import QAbstractNativeEventFilter, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import brain as brain_mod
import config
from brain import Brain
from chat import ChatWindow
from history import History
from pet import Bubble, Pet
from settings import Settings

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
VK_M = 0x4D

# 主动说话的语气轮换，防止「看屏幕」翻来覆去总是同一个腔调。
# 注意：这些不是内置台词，只是每次随机抽一个「方向」写进提示词，
# 台词由模型现场生成。角度/句式/长度三维随机组合，避免输出千篇一律。
VERSION = "v2026.09.08.1540"
STYLES = [
    "先用半句点出他此刻大概在做什么，再自然接一句话",
    "结合屏幕内容给一条务实的建议",
    "指出一个可以改进的小细节",
    "关心他的状态（要具体，别说「在忙什么」这种套话）",
    "提醒他休息一下眼睛或起来走走",
    "好奇追问一句他正在做的事",
    "给他打气加油",
    "感慨一句",
]
FORMS = ["以疑问句结尾", "用感叹句", "平静地陈述", "用反问语气", "只说半句留个话头"]
LENGTHS = ["不超过 15 字", "不超过 25 字", "30 字左右的一两句话"]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", wintypes.POINT),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]


def idle_seconds():
    """键鼠空闲了多少秒。用来判断「人已经离开」。"""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, cb):
        super().__init__()
        self.cb = cb

    def nativeEventFilter(self, eventType, message):
        try:
            msg = MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY:
            self.cb(msg.wParam)
        return False, 0


class SenseWorker(QThread):
    got = Signal(str, object)  # (回复文本, 产生回复时的截图或 None)

    def __init__(self, brain, prompt, image, record=True, kind="auto", fresh=False):
        super().__init__()
        self.brain, self.prompt, self.image = brain, prompt, image
        self.record = record
        self.kind = kind
        self.fresh = fresh

    def run(self):
        self.got.emit(self.brain.once(self.prompt, self.image,
                                      record=self.record, kind=self.kind,
                                      fresh=self.fresh),
                      self.image)


def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor("#185FA5"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("#5DCAA5"))
    p.setFont(QFont("Microsoft YaHei", 28, QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "贾")
    p.end()
    return QIcon(pm)


class FixWorker(QThread):
    """把带助手口气的产出改写成陈述句，而不是直接丢掉。

    实测模型对问句有顽固偏好（"看着不累吗？"），光靠提示词禁令压不干净。
    这里让它自己改写一次：去掉问号和「你」，只留自己的反应。
    """
    got = Signal(str, object)

    def __init__(self, brain, bad_text, image):
        super().__init__()
        self.brain, self.bad, self.image = brain, bad_text, image

    def run(self):
        ask = ("把你刚才那句话改成一句陈述句：去掉问号、去掉「你」和「您」，"
               "只保留你自己的反应和看法，不超过 25 字，"
               "结尾只能用句号、感叹号或省略号。直接输出这一句，不要解释。\n"
               "原句：%s" % self.bad)
        try:
            out = self.brain.once(ask, record=False, fresh=True, kind="fix")
        except Exception:
            out = ""
        self.got.emit(out, self.image)


class App:
    def __init__(self):
        self.cfg = config.load()
        self.brain = Brain(self.cfg)
        self.sensing = False
        self.ticking = False
        self._worker = None
        self._tick_worker = None
        self._fix = None          # 改写「助手口气」的后台线程
        self._fixing = False

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        if self._already_running():
            self.dup = True
            return
        self.dup = False

        self.pet = Pet(self.cfg, self.on_action)
        self.bubble = Bubble(self.cfg, self._continue_from_bubble)
        self._dialogs = {}  # 设置/历史等窗口复用，避免重复弹出
        self.chat = ChatWindow(self.brain, self.cfg, self.bubble, self.pet)
        self.pet.show()
        # 桌宠一动，气泡和对话面板就跟着走（拖动、贴边停靠动画都会触发）
        self.pet.moved.connect(self._on_pet_moved)
        # 气泡要避让对话面板，别压在面板上
        self.bubble.avoid(self.chat)
        self._said = deque(maxlen=12)  # 最近主动说过的话（存完整文本，用于相似度去重）

        self.timer = QTimer()
        self.timer.timeout.connect(self.do_sense)
        self.tick_timer = QTimer()
        self.tick_timer.timeout.connect(self.do_tick)
        self._sync_timer()

        self._tray()
        self._hotkey()

    def _already_running(self):
        """单实例锁：多开一个就多一倍弹窗和 token，必须挡住。

        用内核互斥量而不是 QLocalServer：进程被强杀后命名管道会残留一小会儿，
        导致新实例误判「已有一个在跑」而静默退出（表现为双击后桌宠不出现）。
        互斥量是内核对象，进程一死立即释放，不会残留。
        """
        ERROR_ALREADY_EXISTS = 183
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = wintypes.HANDLE
        self._mutex = k32.CreateMutexW(None, True, "JarvisLite_SingleInstance")
        return k32.GetLastError() == ERROR_ALREADY_EXISTS

    # ---------- 托盘 ----------
    def _dbglog(self, msg):
        """窗口操作黑匣子：点击历史/设置没反应时，看这里就知道死在哪一步。"""
        try:
            from datetime import datetime as _dt

            with open(os.path.join(config.BASE_DIR, "ui_log.txt"), "a",
                      encoding="utf-8") as f:
                f.write("%s %s\n" % (_dt.now().strftime("%H:%M:%S"), msg))
        except Exception:
            pass

    def _tray(self):
        self.tray = QSystemTrayIcon(make_icon(), self.app)
        self.tray.setToolTip("小贾 · 桌宠")
        m = QMenu()
        # 必须显式设置 item 文字色：只给 QMenu 白底的话，深色系统主题下
        # 菜单项文字仍是系统白色 → 白底白字悬停根本看不清
        m.setStyleSheet(
            "QMenu{background:#FFFFFF;border:1px solid #C9CDD4;}"
            "QMenu::item{padding:6px 26px;color:#2B2B2B;}"
            "QMenu::item:selected{background:#185FA5;color:#FFFFFF;}"
            "QMenu::item:disabled{color:#9A9A9A;}"
        )

        def add(label, fn):
            act = QAction(label, self.app)
            act.triggered.connect(fn)
            m.addAction(act)

        ver = QAction(VERSION, self.app)
        ver.setEnabled(False)  # 只读版本标识，方便确认运行的是哪一版
        m.addAction(ver)
        m.addSeparator()

        add("对话 (Ctrl+M)", self.toggle_chat)
        add("历史记录", self.show_history)
        add("桌宠归位", self.reset_pet)
        m.addSeparator()
        self.act_sense = QAction("暂停感知", self.app)
        self.act_sense.triggered.connect(self.toggle_sense)
        m.addAction(self.act_sense)
        add("设置", self.open_settings)
        add("小贾记住了什么", self.open_user_memory)
        m.addSeparator()
        add("退出", self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(
            lambda r: self.toggle_chat() if r == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()
        self._sync_sense_label()

    def _hotkey(self):
        self.filter = HotkeyFilter(lambda _: self.toggle_chat())
        self.app.installNativeEventFilter(self.filter)
        if not ctypes.windll.user32.RegisterHotKey(None, 1, MOD_CONTROL, VK_M):
            self.bubble.say(self.pet, "Ctrl+M 被别的程序占了，用托盘图标唤我", 6000)

    # ---------- 行为 ----------
    def on_action(self, kind, payload):
        if kind == "menu":
            # 重入保护：menu.exec() 是阻塞式模态调用，而桌宠本体右键与托盘右键
            # 走的是同一个入口。连点两次会嵌套 exec，两个菜单事件循环互锁，
            # 表现就是「托盘右键点了没反应、菜单再也不弹」。
            if self.__dict__.get("_menu_open"):
                return
            self._menu_open = True
            try:
                self.tray.contextMenu().exec(payload)
            finally:
                self._menu_open = False
        elif kind == "toggle_sense":
            self.toggle_sense()
        elif kind == "save":
            config.save(self.cfg)
        elif kind == "chat":
            self.toggle_chat()

    def _on_pet_moved(self):
        """桌宠位置变化：让挂在它旁边的窗口一起挪。"""
        try:
            self.bubble.follow()
            self.chat.follow()
        except Exception:
            pass

    def toggle_chat(self):
        if self.chat.isVisible():
            self.chat.hide()
        else:
            self.chat.follow()
            self.chat.show()
            self.chat.raise_()
            self.chat.input.setFocus()

    def toggle_sense(self):
        self.pet.sensing = not self.pet.sensing
        self._sync_sense_label()
        self.bubble.say(self.pet, "感知已开启" if self.pet.sensing else "感知已暂停，我看不见了", 3000)

    def _sync_sense_label(self):
        self.act_sense.setText("暂停感知" if self.pet.sensing else "恢复感知")

    def reset_pet(self):
        """靠边隐藏后找不到它时，一键放回右下角。"""
        self.pet.reset_pos()
        config.save(self.cfg)
        self.bubble.say(self.pet, "我在这儿呢", 3000)

    def _flash_taskbar(self, w):
        """任务栏闪烁提醒：窗口在底层打开时不抢焦点、不遮挡其他应用，
        任务栏图标闪橙光提示用户点它切换上来。"""
        try:
            import ctypes
            from ctypes import wintypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", ctypes.c_ulong),
                    ("uCount", ctypes.c_uint),
                    ("dwTimeout", ctypes.c_ulong),
                ]

            FW_ALL = 0x3
            FW_TIMERNOFG = 0xC  # 一直闪到窗口被激活为止
            info = FLASHWINFO()
            info.cbSize = ctypes.sizeof(FLASHWINFO)
            info.hwnd = int(w.winId())
            info.dwFlags = FW_ALL | FW_TIMERNOFG
            info.uCount = 5
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass

    def _spotlight(self, d):
        """打开时把窗口放到屏幕正中央——保证第一眼就能看到。
        不加高亮边框（用户要求），不置顶不遮挡。"""
        try:
            scr = QApplication.primaryScreen().availableGeometry()
            d.move(
                max(10, scr.center().x() - d.width() // 2),
                max(20, scr.center().y() - d.height() // 2),
            )
        except Exception:
            pass

    def _open_dialog(self, key, factory):
        """从托盘菜单打开窗口：延后一拍 + 非模态 show()。

        直接在菜单项的槽里 exec() 模态对话框，会和菜单自己的事件循环打架
        （卡死同款），所以先让菜单关掉再打开。
        注意：不强制前置（用户要求设置/历史不能盖住其他应用），
        窗口被压住时任务栏里有对应项，点一下即可切换到它。
        """
        out = self._dbglog

        def _go():
            try:
                dlg = self._dlg_map().get(key)
                if dlg is not None and dlg.isVisible():
                    dlg.raise_()
                    dlg.activateWindow()
                    g = dlg.geometry()
                    out("reusing %s at (%d,%d) %dx%d (raise+activate)"
                        % (key, g.x(), g.y(), dlg.width(), dlg.height()))
                    return
                out("opening %s ..." % key)
                d = factory()
                self._dlg_map()[key] = d
                d.show()
                d.raise_()
                d.activateWindow()
                self._spotlight(d)  # 屏幕正中央 + 高亮 3 秒，绝不会错过
                g = d.geometry()
                out("opened %s ok at (%d,%d) %dx%d spotlight=on"
                    % (key, g.x(), g.y(), d.width(), d.height()))
            except Exception as e:
                # 打开失败必须留下线索，否则就是无声无息的「点了没反应」
                import traceback

                err = "".join(traceback.format_exception_only(type(e), e)).strip()
                out("open %s FAILED: %s" % (key, err))
                self.bubble.say(self.pet, "窗口打开失败了：%s" % err[:80], 8000)

        self._dbglog("menu click: %s" % key)
        QTimer.singleShot(0, _go)

    def _dlg_map(self):
        """窗口表（容错：属性万一被外部改动弄丢也能自愈）。

        注意必须用 __dict__ 查，用 getattr 会命中这个方法本身。
        """
        d = self.__dict__.get("_dlg_store")
        if d is None:
            d = {}
            self._dlg_store = d
        return d

    def show_history(self):
        self._open_dialog("history", History)

    def clear_memory(self):
        """清空「对话记录」（流水账）。入口已从托盘挪到设置面板，避免误触。"""
        self.brain.clear_history()
        self.chat.clear()
        self.bubble.say(self.pet, "对话记录清空了", 3000)

    def clear_user_memo(self):
        """清空「长期记忆」（关于用户的提炼事实）。入口同样只在设置面板。"""
        self.brain.clear_user_memo()
        self.bubble.say(self.pet, "关于他的记忆清空了，重新认识一下", 3000)

    def open_user_memory(self):
        """长按托盘的「小贾记住了什么」：直接打开长期记忆文件，看得见、可手改。"""
        path = config.USER_MEMO_PATH
        if not os.path.exists(path):
            self.brain.save_memo("")
        try:
            os.startfile(path)
        except Exception as e:
            self.bubble.say(self.pet, "打不开了：%s" % str(e)[:40], 6000)

    def open_settings(self):
        if not hasattr(self, "pet"):   # 已有一个实例在跑时本进程没有桌宠对象
            return
        self._open_dialog(
            "settings", lambda: Settings(self.cfg, self.on_save, self.pet, self.chat)
        )

    def on_save(self, cfg):
        config.save(cfg)
        self.brain.reload(cfg)
        self.pet.apply_scale(cfg["pet"].get("scale", 1.0))
        self.pet.set_skin(cfg["pet"].get("skin", "cat"))
        self.chat.apply_font(cfg.get("ui", {}).get("font_size", 12))
        self._sync_timer()
        self.bubble.say(self.pet, "设置已保存", 2500)

    # 用户明确说过：要的是「陪伴」，不是「另一个 agent」。
    # 一旦发言里冒出助手口气（提建议、问要不要、提醒休息），就在这里再压一遍。
    ASSISTANT_WORDS = ("要不要", "建议", "记得", "加油", "注意", "休息", "歇",
                       "喝水", "眼睛", "早点", "别忘", "试试", "不如", "加油")

    # 真正发出去之前的最后一道闸：偶发还是会出现「看这么久了，眼睛不酸吗？」
    # 这种助手口气，光靠提示词压不干净。宁可不说话，也不发出这种口气。
    BAN_WORDS = ("要不要", "建议", "记得", "加油", "休息", "歇会儿", "早点睡", "喝水")

    @staticmethod
    def _too_assistant(text):
        # 用户明确说过：老是「你」和「？」让他很不舒服。
        # 这两样正是「另一个 agent 在跟他说话」最明显的特征 → 直接不发。
        if "？" in text or "?" in text:
            return True                      # 问句 = 采访用户
        if "你" in text or "您" in text:
            return True                      # 别点名，说的是「这事儿」不是「你」
        return any(w in text for w in App.BAN_WORDS)

    def _say_final(self, text, image):
        """最后的发出口：去重 + 助手口气双检，通过就弹气泡。"""
        text = (text or "").strip()
        if not text or text.startswith("[ERROR]") or "[SKIP]" in text:
            return
        if self._too_similar(text):
            self._dbglog("skip repeat: %s" % text[:30])
            return
        if self._too_assistant(text):
            self._dbglog("skip assistant-tone: %s" % text[:30])
            return
        self._said.append(text)
        self.bubble.say(self.pet, text, image=image, clickable=True)
        self.pet.set_talking(True)
        QTimer.singleShot(3500, lambda: self.pet.set_talking(False))

    def _retry_statement(self, text, image):
        """带助手口气 → 让它自己改写成陈述句，再走一遍校验（只改一次）。"""
        if self._fixing:
            return
        self._fixing = True
        self._dbglog("rewrite: %s" % text[:30])
        self._fix = FixWorker(self.brain, text, image)
        self._fix.got.connect(self._on_fixed)
        self._fix.start()

    def _on_fixed(self, text, image):
        self._fixing = False
        self._say_final(text, image)

    @staticmethod
    def _bigrams(s):
        s = "".join(ch for ch in s if ch.strip())
        return {s[i:i + 2] for i in range(max(0, len(s) - 1))}

    def _too_similar(self, text):
        """和最近说过的话太像就直接不发——防止连着弹同义句。"""
        g = self._bigrams(text)
        if not g:
            return False
        for old in self._said:
            o = self._bigrams(old)
            if not o:
                continue
            if len(g & o) / float(len(g | o)) >= 0.34:
                return True
        return False

    def _assistant_pressure(self):
        """最近 5 句里有 ≥2 句是助手口气，就该往「陪伴」拉回来了。"""
        recent = list(self._said)[-5:]
        return sum(1 for s in recent
                   if any(w in s for w in self.ASSISTANT_WORDS)) >= 2

    def _vary(self, prompt):
        """注入「最近说过的话 + 角度/句式/长度三维随机」，让主动搭话不重样。"""
        if self._said:
            prompt += ("\n你最近说过这些，不要重复类似内容和开头方式："
                       + "；".join(self._said))
        if self._assistant_pressure():
            prompt += ("\n（注意：你最近几句又滑回「助手口气」了——在提建议、问要不要、"
                       "提醒休息。立刻改回来：只说你自己的反应和看法，"
                       "不要建议、不要问句、不要提醒、别说「加油」。）")
        prompt += (
            "\n这次的表达要求：角度=%s；句式=%s；长度=%s。三者都严格执行，"
            "且开头用词、句式结构必须和上面列过的每一句都不一样。"
            % (random.choice(STYLES), random.choice(FORMS), random.choice(LENGTHS))
        )
        return prompt

    def _continue_from_bubble(self, image, text):
        """双击气泡 → 打开对话面板，带着截图和那句话继续聊。"""
        if self.chat.isVisible() and self.chat.worker:
            return  # 正在流式回复中，不打断
        self.chat.follow()
        self.chat.show()
        self.chat.raise_()
        self.chat.continue_bubble(text, image)

    def _sync_timer(self):
        self.timer.stop()
        self.tick_timer.stop()
        if self.cfg["sense"]["enabled"]:
            self.timer.start(self.cfg["sense"]["interval_sec"] * 1000)
        if self.cfg["tick"]["enabled"]:
            self.tick_timer.start(self.cfg["tick"]["interval_sec"] * 1000)

    def _away(self):
        """人不在（键鼠空闲超阈值）时别自言自语，省 token。"""
        idle = self.cfg.get("idle", {})
        if not idle.get("enabled", True):
            return False
        return idle_seconds() > idle.get("threshold_sec", 300)

    # ---------- 屏幕感知 ----------
    def do_sense(self):
        if not self.cfg["sense"]["enabled"] or not self.pet.sensing:
            return
        if self._away():
            return
        if not self.brain.ready or self.sensing or self.ticking:
            return
        self.sensing = True
        sense = self.cfg["sense"]
        scale = sense.get("shot_scale", 0.85)
        quality = sense.get("shot_quality", 82)
        scope = sense.get("shot_scope", "window")
        shot = brain_mod.grab_screen(scale=scale, quality=quality,
                                     foreground=(scope != "screen"))
        prompt = self._vary(sense["prompt"])
        # 告诉它自己现在是什么样子，屏幕里那个卡通形象就是本尊，不是屏幕内容
        prompt += ("\n（你现在是「%s」的样子，画面里那个卡通形象就是你自己，"
                   "不是屏幕里的内容。）" % self.pet.label(self.pet._skin))
        # fresh=True：感知提示词本身已带「最近说过的话」，不必再捎 12 条历史，
        # 否则每 30 秒都要把上一轮的 500 字提示词再发一遍，纯烧 token
        w = SenseWorker(self.brain, prompt, shot, record=True, kind="auto", fresh=True)
        w.got.connect(self._on_sense)
        self._worker = w
        w.start()

    def _on_sense(self, text, image):
        self.sensing = False
        if not text or text.startswith("[ERROR]") or "[SKIP]" in text:
            return
        text = text.strip()
        if self._too_similar(text):
            self._dbglog("skip repeat: %s" % text[:30])
            return
        if self._too_assistant(text):
            self._retry_statement(text, image)   # 别丢掉，让它改成陈述句再说
            return
        self._say_final(text, image)

    # ---------- 定时主动搭话（不看屏幕，几乎零延迟） ----------
    def do_tick(self):
        if not self.cfg["tick"]["enabled"] or not self.pet.sensing:
            return
        if self._away():
            return
        if not self.brain.ready or self.ticking or self.sensing:
            return
        self.ticking = True
        now = datetime.now()
        prompt = (
            self.cfg["tick"]["prompt"]
            .replace("{time}", now.strftime("%H:%M"))
            .replace("{date}", now.strftime("%Y-%m-%d"))
        )
        w = SenseWorker(self.brain, self._vary(prompt), None, record=True,
                        kind="auto", fresh=True)
        w.got.connect(self._on_tick)
        self._tick_worker = w
        w.start()

    def _on_tick(self, text, image):
        self.ticking = False
        if not text or text.startswith("[ERROR]") or "[SKIP]" in text:
            return
        text = text.strip()
        if self._too_similar(text):
            self._dbglog("skip repeat: %s" % text[:30])
            return
        if self._too_assistant(text):
            self._retry_statement(text, None)
            return
        self._say_final(text, None)

    # ---------- 生命周期 ----------
    def run(self):
        if self.dup:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                None, "小贾",
                "小贾已经在运行了。\n\n"
                "如果看不到它，可能是靠边隐藏了：把鼠标移到屏幕左右边缘，"
                "或用托盘图标 → 桌宠归位。",
            )
            return 0
        if not self.brain.ready:
            self.bubble.say(self.pet, "右键我 → 设置，填 API Key 就能聊了", 12000)
        elif self.cfg["sense"]["enabled"]:
            # 启动后先来一次，否则要等满一个间隔才看到第一句话
            QTimer.singleShot(15000, self.do_sense)
        return self.app.exec()

    def quit(self):
        self.pet.save_pos()
        config.save(self.cfg)
        ctypes.windll.user32.UnregisterHotKey(None, 1)
        self.tray.hide()
        self.app.quit()


if __name__ == "__main__":
    os.chdir(config.BASE_DIR)
    sys.exit(App().run())
