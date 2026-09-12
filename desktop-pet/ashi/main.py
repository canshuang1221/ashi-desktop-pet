import ctypes
import os
import random
import re
import sys
import time
from collections import deque
from ctypes import wintypes
from datetime import datetime

from PySide6.QtCore import (QAbstractNativeEventFilter, QCoreApplication, Qt,
                            QThread, QTimer, Signal)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import brain as brain_mod
import config
import activity
from brain import Brain
from chat import ChatWindow
from history import History, Memo
from pet import Bubble, Pet
from settings import Settings

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
VK_M = 0x4D

# 实例之间说话用的本地 socket。新实例启动时先用它请老实例**优雅退出**
# （对方会跑 quit() → tray.hide() → 托盘图标干净反注册）。
# 直接强杀的话 Qt 没机会反注册，通知区就会留下"僵尸图标"；攒几个之后外壳
# 清理时会把活着那条的注册也一并弄失效 —— 表现就是托盘图标点不动。
CTL_SOCKET = "ashi-ctl"

# Explorer 重建任务栏（重启/崩溃恢复）时会广播这个消息。收到就必须重新注册
# 托盘图标 —— QSystemTrayIcon 自己不会补，它内部还认为 visible=True。
try:
    WM_TASKBAR_CREATED = ctypes.windll.user32.RegisterWindowMessageW("TaskbarCreated")
except Exception:
    WM_TASKBAR_CREATED = 0

# ctl_send 只在没有 QApplication 时（如 --quit）自己造一个，造了得有人持有
_CTL_APP = None


def ctl_send(cmd, timeout=1200):
    """给已经在跑的实例发一条命令。返回对方是否应答。

    连不上 = 没人在跑（强杀留下的残留管道名是连不上的）。
    """
    global _CTL_APP
    inst = QCoreApplication.instance()
    if inst is None:
        _CTL_APP = QCoreApplication([])
        inst = _CTL_APP
    s = QLocalSocket()
    s.connectToServer(CTL_SOCKET)
    if not s.waitForConnected(timeout):
        s.abort()
        return False
    try:
        s.write(cmd.encode("utf-8"))
        s.flush()
        s.waitForBytesWritten(timeout)
        s.waitForDisconnected(timeout)   # 对方答完就断开
        return True
    finally:
        s.abort()
        s.deleteLater()

# 主动说话的语气轮换，防止「看屏幕」翻来覆去总是同一个腔调。
# 注意：这些不是内置台词，只是每次随机抽一个「方向」写进提示词，
# 台词由模型现场生成。角度/句式/长度三维随机组合，避免输出千篇一律。
def build_version():
    """当前跑的是哪一版 —— 从文件时间推出来，不用手改常量。

    以前是个硬编码字符串，所以「版本号永远不变」；而且它只显示在托盘菜单里 ——
    托盘一旦点不动，连版本都查不到了。现在改成自动算：
    打包版看 exe 的修改时间，源码运行看项目里最新那个 .py 的修改时间
    （改任何文件版本都会变），并写进日志，托盘坏了也能查。
    """
    if getattr(sys, "frozen", False):
        targets, tag = [sys.executable], "-exe"
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        try:
            targets = [os.path.join(here, f) for f in os.listdir(here)
                       if f.endswith(".py")]
        except OSError:
            targets = []
        tag = "-src"
    newest = 0.0
    for p in targets:
        try:
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            pass
    if not newest:
        return "v?"
    return "v%s%s" % (datetime.fromtimestamp(newest).strftime("%Y.%m.%d.%H%M"), tag)


VERSION = build_version()
STYLES = [
    "先用半句说清画面里正在发生什么，再自然接一句自己的反应",
    "吐槽画面里最离谱的那一处",
    "替画面里的人捏把汗",
    "说一个只有你注意到的小细节（某个角落、配色、字写得怪、图标有意思）",
    "感慨一句，像看剧看到某个桥段那样",
    "直接对画面里的东西下个自己的判断（喜欢/嫌弃/看不懂）",
]
# 这份方向表里**一条都不能是**「给建议 / 提改进 / 劝休息 / 打气 / 追问」——
# 那些方向产出的句子必然含 BAN_WORDS 或被判成助手口气，最后被出口闸整句丢掉，
# 等于每次白烧一次接口调用（历史上就是这么浪费的，实测全被拦）。
FORMS = ["用感叹句", "平静地陈述", "只说半句留个话头"]
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
    """收原生消息：全局热键 + 「任务栏重建」广播。

    任务栏重建（explorer 重启/崩溃恢复）会让所有托盘图标失效，必须重新注册，
    而 QSystemTrayIcon 自己不会补 —— 它内部还认为 visible=True。
    所以顺路在这里接一手 WM_TASKBAR_CREATED。
    """

    def __init__(self, cb, on_taskbar=None):
        super().__init__()
        self.cb = cb
        self.on_taskbar = on_taskbar

    def nativeEventFilter(self, eventType, message):
        try:
            msg = MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY:
            self.cb(msg.wParam)
        elif WM_TASKBAR_CREATED and msg.message == WM_TASKBAR_CREATED:
            if self.on_taskbar is not None:
                self.on_taskbar()
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


def make_icon(pet_name="桌宠"):
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor("#185FA5"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("#5DCAA5"))
    p.setFont(QFont("Microsoft YaHei", 28, QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, pet_name[:1])
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
               "结尾只能用句号、感叹号或省略号。"
               "另外：不要提屏幕上的光标/鼠标（什么停着、转圈、卡住），"
               "换个画面里真正有内容的东西说。"
               "直接输出这一句，不要解释。\n"
               "原句：%s" % self.bad)
        try:
            out = self.brain.once(ask, record=False, fresh=True, kind="fix")
        except Exception:
            out = ""
        self.got.emit(out, self.image)


class ActivityWorker(QThread):
    """把攒下来的活动标签归纳成「今天干了什么」。

    后台跑，避免那一次额外的接口调用卡住界面。
    """

    def __init__(self, brain):
        super().__init__()
        self.brain = brain

    def run(self):
        try:
            n = activity.count()
            out = self.brain.once(activity.summary_prompt(), record=False,
                                  fresh=True, kind="activity")
            k = activity.save_summary(out, n)
            if k:
                with open(os.path.join(config.BASE_DIR, "log.txt"), "a",
                          encoding="utf-8") as f:
                    f.write("[activity] 今日足迹已归纳 %d 条\n" % k)
        except Exception:
            pass


class DigestWorker(QThread):
    """把还没沉淀的对话 + 活动，提炼成一份更新后的长期记忆。

    以前是「聊一轮就提炼一次」，聊得越多、长期记忆越臃肿。现在改成
    每天（启动时 + 之后每小时）跑一次：把上一天之后的素材一次性沉淀，
    断档也能补上。后台跑，避免那次接口调用卡住界面。
    """

    def __init__(self, brain):
        super().__init__()
        self.brain = brain

    def run(self):
        try:
            days = self.brain.pending_digest_days()
            if not days:
                return
            n = self.brain.digest_memory(days)
            if n:
                with open(os.path.join(config.BASE_DIR, "log.txt"), "a",
                          encoding="utf-8") as f:
                    f.write("[digest] 沉淀 %s，长期记忆 %d 条\n"
                            % ("、".join(days[-3:]), n))
        except Exception:
            pass


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
        self._act = None          # 归纳「今日足迹」的后台线程
        self._summarizing = False
        self._digest = None       # 沉淀长期记忆的后台线程
        self._digesting = False

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        # 先把已经在跑的老实例请走：它会自己跑 quit() → tray.hide() → 托盘图标
        # 干净反注册。直接强杀正是通知区攒"僵尸图标"的根源，攒多了会把活着那条
        # 的注册也带得失效 —— 表现就是托盘图标点不动。
        self._evict_old()
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

        # 长期记忆的沉淀检查。启动时会立刻来一次（见 run()），这里每小时
        # 再看一眼：为的是跨天不关机的场景也能及时沉淀，而不是干等重启。
        self.digest_timer = QTimer()
        self.digest_timer.timeout.connect(self.check_digest)
        self.digest_timer.start(60 * 60 * 1000)

        self._tray()
        self._hotkey()
        # 已经是唯一实例了，开通道接"请退出"这类指令
        self._ctl_server()
        # 兜底：任何不走 quit() 的退出路径，也把托盘图标收掉
        self.app.aboutToQuit.connect(self._hide_tray)

    # ---------- 实例之间 ----------
    def _evict_old(self, timeout=3.0):
        """请已经在跑的那个阿拾自己退出，再接手。

        为什么要费这个劲：强杀会让 Qt 没机会调 tray.hide() 反注册托盘图标，
        通知区就留下"僵尸图标"；攒几个之后外壳清理时会把活着那条的注册也一并
        弄失效 → 托盘图标点不动。好好说话就没这个问题。

        对方不应答（老版本没有这条通道）就什么都不做，交给下面的单实例判定。
        """
        if not ctl_send("quit"):
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not ctl_send("ping", 400):
                time.sleep(0.4)     # 再宽限一下，等它把内核锁也释放掉
                self._dbglog("old instance left politely")
                return True
            time.sleep(0.25)
        self._dbglog("old instance ignored quit (%.1fs)" % timeout)
        return False

    def _ctl_server(self):
        """开一条本地 socket，接受"请退出"这类指令。"""
        self._ctl = QLocalServer(self.app)
        self._ctl.newConnection.connect(self._on_ctl)
        if not self._ctl.listen(CTL_SOCKET):
            # 名字被上一次强杀留下的残留管道占着 —— 清掉再试一次
            QLocalServer.removeServer(CTL_SOCKET)
            self._ctl.listen(CTL_SOCKET)
        self._dbglog("ctl listening: %s" % self._ctl.isListening())

    def _on_ctl(self):
        conn = self._ctl.nextPendingConnection()
        if conn is None:
            return
        cmd = ""
        try:
            conn.waitForReadyRead(500)
            cmd = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            conn.write(b"ok")
            conn.flush()
            conn.waitForBytesWritten(300)
            conn.disconnectFromServer()
        except Exception:
            pass
        finally:
            try:
                conn.deleteLater()
            except Exception:
                pass
        self._dbglog("ctl: %s" % cmd)
        if cmd == "quit":
            # 别在这个回调里直接退（事件还在派发），让事件循环转一圈再走
            QTimer.singleShot(0, self.quit)

    def _hide_tray(self):
        try:
            tray = getattr(self, "tray", None)
            if tray is not None:
                tray.hide()
        except Exception:
            pass

    def _already_running(self):
        """单实例锁：多开一个就多一倍弹窗和 token，必须挡住。

        用内核互斥量而不是 QLocalServer：进程被强杀后命名管道会残留一小会儿，
        导致新实例误判「已有一个在跑」而静默退出（表现为双击后桌宠不出现）。
        互斥量是内核对象，进程一死立即释放，不会残留。
        """
        ERROR_ALREADY_EXISTS = 183
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = wintypes.HANDLE
        self._mutex = k32.CreateMutexW(None, True, "ashi_SingleInstance")
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
        self.tray = QSystemTrayIcon(make_icon(self.cfg["pet"]["name"]), self.app)
        self.tray.setToolTip("%s · 桌宠" % self.cfg["pet"]["name"])
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
        add("%s记住了什么" % self.cfg["pet"]["name"], self.open_user_memory)
        add("修复托盘图标", self.repair_tray)
        m.addSeparator()
        add("退出", self.quit)

        # 「让路」挂在菜单自己的信号上，而不是挂在 on_action 里。
        # 原因：托盘右键走的是 setContextMenu 的内部路径，**根本不经过 on_action**
        # —— 那条路从来没让过路，菜单会被 TOPMOST 的桌宠/气泡压住，看着就像"点不动"。
        # aboutToShow / aboutToHide 两条路都会触发，挂这里才能一次覆盖两边。
        m.aboutToShow.connect(self._menu_show)
        m.aboutToHide.connect(self._menu_hide)

        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._sync_sense_label()

    # ---------- 托盘 / 菜单 ----------
    def _on_tray_activated(self, reason):
        """托盘图标被点时触发。

        刻意留一行日志：托盘"点不动"时，有这行就说明点击到了程序（问题在外壳那边
        的注册），没有就说明点击根本没送到 —— 这是最省事的判别依据。
        """
        self._dbglog("tray activated: %s" % reason)
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_chat()

    def _menu_show(self):
        self._dbglog("menu shown -> pet/bubble give way")
        try:
            self.pet.suspend_topmost()
            self.bubble.suspend_topmost()
        except Exception:
            pass
        # 万一 aboutToHide 没来（菜单被外部关闭等），也不能让桌宠永久失去置顶
        QTimer.singleShot(self.MENU_LOCK_TIMEOUT * 1000, self._menu_hide)

    def _menu_hide(self):
        for restore in (self.pet.resume_topmost, self.bubble.resume_topmost):
            try:
                restore()
            except Exception:
                pass

    def repair_tray(self):
        """重建托盘图标。

        外壳把图标条目弄失效之后，Qt 内部仍认为 visible=True，所以光 show() 没用，
        必须先 hide() 把状态复位再 show() 重新注册。
        入口在菜单里 —— 托盘点不动时，**桌宠右键那条路还是好的**，用活着的通道救它。
        """
        try:
            self.tray.hide()
            self.tray.show()
            self._dbglog("tray re-registered by user")
        except Exception as e:
            self._dbglog("tray re-register FAILED: %s" % e)

    def _hotkey(self):
        # 第二个回调：任务栏重建（explorer 重启）时重新注册托盘图标，
        # 否则图标会一直失效
        self.filter = HotkeyFilter(lambda _: self.toggle_chat(), self.repair_tray)
        self.app.installNativeEventFilter(self.filter)
        if not ctypes.windll.user32.RegisterHotKey(None, 1, MOD_CONTROL, VK_M):
            self.bubble.say(self.pet, "Ctrl+M 被别的程序占了，用托盘图标唤我", 6000)

    # ---------- 行为 ----------
    # 菜单最多允许开着这么久（秒），超时视为卡死
    MENU_LOCK_TIMEOUT = 20

    def on_action(self, kind, payload):
        if kind == "menu":
            # 只有【桌宠本体右键】会走到这里；托盘右键由 setContextMenu 在 Qt 内部
            # 处理，不经过本函数（所以"让路"改挂在菜单信号上了，见 _menu_show）。
            # 重入保护：exec() 是阻塞式模态调用，连点两次会嵌套 exec，两个菜单
            # 事件循环互锁，表现就是「菜单再也不弹」。
            locked = self.__dict__.get("_menu_open")
            if locked:
                held = time.time() - self.__dict__.get("_menu_at", 0)
                # 超时自愈：exec() 万一真回不来，也不能让菜单永久点不动
                if held < self.MENU_LOCK_TIMEOUT:
                    # 留痕：有这行说明点击到了程序、是被重入锁挡下的；
                    # 没这行又没 menu shown，就说明点击根本没送到程序
                    self._dbglog("menu skipped: locked %.1fs" % held)
                    return
                self._dbglog("menu lock timeout -> force reset")
            self._dbglog("menu exec (pet right-click)")
            self._menu_open = True
            self._menu_at = time.time()
            try:
                self.tray_menu.exec(payload)
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
        self._open_dialog("history", lambda: History(self.cfg))

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
        """托盘「记住了什么」：弹窗显示长期记忆，看得见、可手改。

        以前是拿 os.startfile 打开 user_memory.md，但 .md 在系统里没有
        关联程序时 Windows 会静默失败——点了菜单像没反应。改成自己弹窗。
        """
        self._open_dialog("memo", lambda: Memo(self.cfg))

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
        self.pet.set_skin(cfg["pet"].get("skin", "pic_fox"))
        self.chat.apply_font(cfg.get("ui", {}).get("font_size", 12))
        self._refresh_name()
        self._sync_timer()
        self.bubble.say(self.pet, "设置已保存", 2500)

    def _refresh_name(self):
        """改完名字立刻反映到托盘提示、图标和菜单项上，不用重启。"""
        name = self.cfg["pet"].get("name") or "桌宠"
        self.tray.setToolTip("%s · 桌宠" % name)
        self.tray.setIcon(make_icon(name))
        menu = self.tray.contextMenu()
        if menu is not None:
            for act in menu.actions():
                if act.text().endswith("记住了什么"):
                    act.setText("%s记住了什么" % name)

    # 真正发出去之前的最后一道闸：偶发还是会出现「看这么久了，眼睛不酸吗？」
    # 这种助手口气，光靠提示词压不干净。宁可不说话，也不发出这种口气。
    #
    # 注意「劝休息」这类句子常常没有问号也不带「你」，
    # 实测漏过网的两句：
    #   「屏幕太暗了，眼睛盯着容易累，眨眨眼再继续看吧。」
    #   「这屏幕亮得跟个小太阳似的，眼睛该出去透透气了。」
    # 所以眼睛/累/透气/歇/活动这些词也必须一起拦。
    BAN_WORDS = ("要不要", "建议", "记得", "加油", "休息", "歇", "喝水",
                 "眼睛", "累", "眨", "透气", "活动一下", "走走", "走动",
                 "脖子", "腰", "早点睡", "熬夜", "身体", "保养", "护眼",
                 # 光标/鼠标：静态画面上最容易抓到的"细节"，于是模型反复拿它当话题，
                 # 说它停着/转圈/卡住 —— 可屏幕明明有内容（用户查了截图确认过）。
                 # 用户明确要求过别提，这里硬封死。
                 "光标", "鼠标")

    # 用户明确说过：要的是「陪伴」，不是「另一个 agent」。
    # 出现这些软信号不一定该拦，但连着来几句就说明又滑回助手口气了，
    # 这时会在提示词里拉一把（见 _assistant_pressure）。
    ASSISTANT_WORDS = BAN_WORDS + ("注意", "早点", "别忘", "试试", "不如",
                                   "可以考虑", "最好")

    @staticmethod
    def _too_assistant(text):
        # 用户明确说过：老是「你」和「？」让他很不舒服。
        # 这两样正是「另一个 agent 在跟他说话」最明显的特征 → 直接不发。
        if "？" in text or "?" in text:
            return True                      # 问句 = 采访用户
        if "你" in text or "您" in text:
            return True                      # 别点名，说的是「这事儿」不是「你」
        return any(w in text for w in App.BAN_WORDS)

    # 允许的活动标签（和 config 里感知提示词给模型的列表保持一致）
    ACTIVITY_TAGS = ("看视频", "看直播", "听音乐", "写代码", "剪视频", "修图",
                     "打游戏", "看文档", "写文档", "聊天", "逛网页", "买东西",
                     "学习", "摸鱼", "发呆", "其它")

    @classmethod
    def _split_activity(cls, text):
        """把回复开头的活动标签拆出来，剩下的才是要说的话。

        实测模型常常只写 [修图] 而漏掉「活动:」前缀，所以前缀可省；
        但标签必须落在允许列表里，免得把正文里的 [xxx] 误当标签。
        """
        text = (text or "").strip()
        m = re.match(
            r"^\s*[\[【]\s*(?:活动\s*[:：]\s*)?([^\]】]{1,8})\s*[\]】]\s*(.*)$",
            text, re.S)
        if not m:
            return "", text
        tag = m.group(1).strip()
        if tag not in cls.ACTIVITY_TAGS:
            # 不在允许列表里：只有明确带「活动:」前缀时才认
            if not re.match(r"^\s*[\[【]\s*活动", text):
                return "", text
        return tag, m.group(2).strip()

    def _note_activity(self, tag):
        """记一条足迹；攒够了就后台归纳一次。"""
        if not tag:
            return
        activity.add(tag)
        if activity.need_summary() and not self._summarizing:
            self._summarizing = True
            self._act = ActivityWorker(self.brain)
            self._act.finished.connect(self._activity_done)
            self._act.start()

    def _activity_done(self):
        self._summarizing = False

    def check_digest(self):
        """有没沉淀的日子就后台沉淀一次长期记忆。

        没配 API Key、或已经在跑、或没有待沉淀的日子，都直接跳过——
        所以它每小时调一次也不会有开销。
        """
        if self._digesting or not self.brain.ready:
            return
        try:
            days = self.brain.pending_digest_days()
        except Exception:
            return
        if not days:
            return
        self._digesting = True
        self._digest = DigestWorker(self.brain)
        self._digest.finished.connect(self._digest_done)
        self._digest.start()

    def _digest_done(self):
        # 注意：这里是线程 finished 信号里的槽，不能顺手把 self._digest 置空
        # ——此刻它还持有正在收尾的 QThread，引用归零会直接崩溃。
        self._digesting = False

    def _save_shot(self, data_url, keep):
        """把这次的截图存下来，只保留最近 keep 张（0 = 不保存）。

        每次覆盖一张的话，回头看「它当时看到了啥」就没依据了；
        留几张的体积也就 1MB 出头。
        """
        if not data_url or keep <= 0:
            return
        try:
            import base64
            import glob
            d = os.path.join(config.BASE_DIR, "shots")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "shot_%s.jpg"
                             % datetime.now().strftime("%Y%m%d-%H%M%S"))
            with open(p, "wb") as f:
                f.write(base64.b64decode(data_url.split(",", 1)[1]))
            files = sorted(glob.glob(os.path.join(d, "shot_*.jpg")))
            for old in files[:-int(keep)]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    def _say_final(self, text, image):
        """最后的发出口：去重（整句 + 用滥的词）+ 助手口气，通过才弹气泡。"""
        text = (text or "").strip()
        if not text or text.startswith("[ERROR]") or "[SKIP]" in text:
            return
        if self._too_similar(text):
            self._dbglog("skip repeat: %s" % text[:30])
            return
        word = self._too_repetitive(text)
        if word:
            # 措辞不一样但又在嚼同一个词（连着几句"光标…"就是这么漏的）
            self._dbglog("skip overused word %s: %s" % (word, text[:30]))
            return
        if self._too_assistant(text):
            self._dbglog("skip assistant-tone: %s" % text[:30])
            return
        self._said.append(text)
        # 到这里才记进当天记忆：能进来的都是真正会弹出来的话
        self.brain.note_reply(text, kind="auto", tag=getattr(self, "_pending_tag", ""))
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

    # ---------- 「用滥了的词」检测 ----------
    # _too_similar 看的是**整句**相似度，措辞一变就漏：实测连着 5 句都在说"光标"
    # （「光标半天没动」「光标在原地打转」「光标停这么久」…）没有一句整句相似，
    # 于是全被放行。所以再补一层**词级**的：某个相邻二字组合在最近几句里频繁
    # 出现，就是"这个词被反复咀嚼了"。
    # 中文没分词，用 2-gram 近似就够 —— 关键是按**句**计数（df）而不是按出现次数，
    # 这样才能准确抓到"连着好几句都在说同一个词"，也不会因为某句里重复两次就误判。
    OVERUSED_N = 10      # 回看最近几句
    OVERUSED_K = 3       # 出现在 >= 3 句里就算用滥
    # 两个字都在这里面的 2-gram 不参与统计，免得把「这是」「了的」这类常见搭配
    # 误判成用滥。只挡最虚的那批字。
    STOP_CHARS = ("的了是在我他她它你您没和与就都也还很太这那不有个一二三"
                  "两吧呢啊哦呀吗把被给对会要能可上下中里外多少又再只")

    def _overused(self):
        """最近几句里被反复用到的二字组合。"""
        df = {}
        for s in list(self._said)[-self.OVERUSED_N:]:
            seen = set()
            for g in self._bigrams(s or ""):
                if g in seen:
                    continue
                if g[0] in self.STOP_CHARS and g[1] in self.STOP_CHARS:
                    continue
                seen.add(g)
                df[g] = df.get(g, 0) + 1
        return {g for g, c in df.items() if c >= self.OVERUSED_K}

    def _too_repetitive(self, text):
        """这句话里有没有已经用滥的词。命中就返回那个词，没有返回空串。"""
        bad = self._overused()
        if not bad:
            return ""
        for g in self._bigrams(text or ""):
            if g in bad:
                return g
        return ""

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
        # 光列句子不够 —— 模型会换措辞、但接着嚼同一个词（"光标半天没动"→
        # "光标在原地打转"）。所以把"用滥了的词"直接点名，让它换说法或换话题。
        bad = self._overused()
        if bad:
            prompt += ("\n最近你反复在用这几个词，听腻了："
                       + "、".join(sorted(bad)[:6])
                       + "。这次换说法，或者干脆换个话题。")
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
        self._save_shot(shot, sense.get("keep_shots", 8))
        prompt = config.render(self._vary(sense["prompt"]), self.cfg)
        # 告诉它自己现在是什么样子，屏幕里那个卡通形象就是本尊，不是屏幕内容
        prompt += ("\n（你现在是「%s」的样子，画面里那个卡通形象就是你自己，"
                   "不是屏幕里的内容。）" % self.pet.label(self.pet._skin))
        # fresh=True：感知提示词本身已带「最近说过的话」，不必再捎 12 条历史，
        # 否则每 30 秒都要把上一轮的 500 字提示词再发一遍，纯烧 token
        # record=False：不要在模型返回时就写记忆。被拦掉的句子（问号/助手口气）
        # 也走这条路，写了就等于历史里出现它从没说过的话。发出后再由 _say_final 记。
        w = SenseWorker(self.brain, prompt, shot, record=False, kind="auto", fresh=True)
        w.got.connect(self._on_sense)
        self._worker = w
        w.start()

    def _on_sense(self, text, image):
        self.sensing = False
        # 不管这次说没说话，都把「距上次感知的这段时间」记到当前活动上。
        # 只在它开口时才计时的话，时长会被严重低估（它可能好几分钟才说一句）。
        activity.tick()
        if not text or text.startswith("[ERROR]") or "[SKIP]" in text:
            return
        # 先把活动标签摘出来记账（这是「今日足迹」的数据来源，与用户说不说话无关）
        tag, body = self._split_activity(text)
        self._pending_tag = tag          # 留给 _say_final 写记忆时带上
        self._note_activity(tag)
        text = body
        if not text or "[SKIP]" in text:
            return
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
        prompt = config.render(prompt, self.cfg)
        w = SenseWorker(self.brain, self._vary(prompt), None, record=False,
                        kind="auto", fresh=True)
        w.got.connect(self._on_tick)
        self._tick_worker = w
        w.start()

    def _on_tick(self, text, image):
        self.ticking = False
        # 定时搭话没有活动标签，清掉上一条感知留下的，免得给它错标
        self._pending_tag = ""
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
                None, self.cfg["pet"]["name"],
                "%s已经在运行了。\n\n" % self.cfg["pet"]["name"] +
                "如果看不到它，可能是靠边隐藏了：把鼠标移到屏幕左右边缘，"
                "或用托盘图标 → 桌宠归位。",
            )
            return 0
        if not self.brain.ready:
            self.bubble.say(self.pet, "右键我 → 设置，填 API Key 就能聊了", 12000)
        else:
            # 每天首次启动：把上一天之后的对话/活动沉淀成长期记忆。
            # 等几秒再跑，别跟启动后那第一句感知挤在一起抢接口。
            QTimer.singleShot(8000, self.check_digest)
            if self.cfg["sense"]["enabled"]:
                # 启动后先来一次，否则要等满一个间隔才看到第一句话
                QTimer.singleShot(15000, self.do_sense)
        return self.app.exec()

    def quit(self):
        # 留痕：有这行 = 走的是正常退出（托盘图标会被干净反注册，不留幽灵图标）；
        # 日志里没有这行而进程却没了 = 被强杀或崩溃，那才会在通知区留僵尸图标。
        self._dbglog("quit(): saving config + hiding tray")
        self.pet.save_pos()
        config.save(self.cfg)
        ctypes.windll.user32.UnregisterHotKey(None, 1)
        self._wait_threads()
        self.tray.hide()
        self.app.quit()

    def _wait_threads(self):
        """退出前等后台线程收尾。

        直接 quit 的话 Qt 会开始销毁对象，而线程可能还在跑（比如正在解析
        接口返回），它回过来一访问已经析构的 QObject 就是硬崩溃 ——
        没有 Traceback、日志也断在半截，非常难查。
        """
        for th in (self._worker, self._tick_worker, self._fix, self._act, self._digest):
            try:
                if th is not None and th.isRunning():
                    th.wait(2000)
            except Exception:
                pass
        try:
            self.chat.shutdown()
        except Exception:
            pass


def _enable_crash_log():
    """崩溃黑匣子：段错误 / Qt 硬崩溃时把 Python 调用栈写进 crash.log。

    这一大类崩溃不会产生 Traceback，日志会直接断在半截（阿拾崩的那次就是
    这样：最后一条是正常气泡，后面什么都没有），光看现有日志只能靠猜。
    faulthandler 是标准库，接上零成本，下次再崩就能直接看到栈。
    """
    try:
        import faulthandler
        f = open(os.path.join(config.BASE_DIR, "crash.log"), "a", encoding="utf-8")
        # 版本号也写这里 —— 它同时显示在托盘菜单里，但托盘一旦点不动就查不到了，
        # 所以必须另留一份在日志里
        f.write("\n===== 启动 %s  %s =====\n"
                % (VERSION, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        f.flush()
        try:
            with open(os.path.join(config.BASE_DIR, "log.txt"), "a",
                      encoding="utf-8") as g:
                g.write("%s [boot] %s pid=%d\n"
                        % (datetime.now().strftime("%H:%M:%S"), VERSION, os.getpid()))
        except Exception:
            pass
        faulthandler.enable(file=f, all_threads=True)
        globals()["_crash_log_file"] = f    # 持有引用，否则文件被回收就失效了
    except Exception:
        pass


if __name__ == "__main__":
    os.chdir(config.BASE_DIR)
    # --quit：请已经在跑的实例优雅退出（它会自己 tray.hide() 收掉托盘图标），
    # 不弹任何界面。桌面「关闭阿拾」用它取代过去的强杀 —— 强杀正是通知区
    # 攒"僵尸图标"的根源。
    if "--quit" in sys.argv:
        sys.exit(0 if ctl_send("quit") else 1)
    _enable_crash_log()
    sys.exit(App().run())
