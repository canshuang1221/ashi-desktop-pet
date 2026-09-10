import base64
import html
import os

import config

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QTextBrowser, QVBoxLayout, QWidget,
)

BG = "#FFFFFF"
LINE = "#185FA5"


class StreamWorker(QThread):
    delta = Signal(str)
    failed = Signal(str)

    def __init__(self, brain, text, image_b64=None, fresh=False, kind="chat"):
        super().__init__()
        self.brain, self.text, self.image = brain, text, image_b64
        self.fresh = fresh  # True=全新对话，不带历史记录上下文
        self.kind = kind

    def run(self):
        for chunk in self.brain.stream(self.text, self.image,
                                       fresh=self.fresh, kind=self.kind):
            if chunk.startswith("[ERROR]"):
                self.failed.emit(chunk[7:])
                return
            self.delta.emit(chunk)


class ChatWindow(QWidget):
    """桌宠旁的对话面板。"""

    def __init__(self, brain, cfg, bubble, pet):
        super().__init__()
        self.brain, self.cfg, self.bubble, self.pet = brain, cfg, bubble, pet
        self.msgs = []          # [(who, text, is_notice)]，微信式气泡按序渲染
        self._pt = 12
        self.worker = None
        self.note_worker = None
        self.drag = None

        self.setWindowTitle("小贾")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.resize(420, 560)
        self._build()
        self._render()   # 先渲染空态提示文案

    def _build(self):
        self.setStyleSheet(
            "QWidget#root{background:%s;border:1px solid %s;border-radius:12px;}"
            "QLabel{color:#185FA5;}" % (BG, LINE)
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        bar = QHBoxLayout()
        title = QLabel("小贾 · 桌宠对话")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Medium))
        self.tip = QLabel("")
        self.tip.setStyleSheet("color:#888780;font-size:11px;")
        close = QPushButton("×")
        close.setFixedSize(24, 24)
        close.setStyleSheet("QPushButton{border:none;color:#5F5E5A;font-size:16px;}"
                            "QPushButton:hover{color:#A32D2D;}")
        close.clicked.connect(self.hide)
        bar.addWidget(title)
        bar.addWidget(self.tip)
        bar.addStretch(1)
        bar.addWidget(close)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        # 链接统一交给系统打开：截图链接点开的是图片查看器，
        # 而不是被当成「文档导航」去渲染 jpg 二进制（那会显示成乱码且回不去）
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(QDesktopServices.openUrl)
        # 微信观感：浅灰聊天底 + 白色/绿色气泡浮在上面
        self.view.setStyleSheet(
            "QTextBrowser{background:#F2F3F5;border:1px solid #D3D1C7;"
            "border-radius:8px;padding:8px;font-size:13px;}"
        )

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("说点什么…  Enter 发送 · Shift+Enter 换行")
        self.input.setFixedHeight(74)
        self.input.setStyleSheet(
            "QPlainTextEdit{background:#F7F9FC;border:1px solid #D3D1C7;"
            "border-radius:8px;padding:6px;font-size:13px;}"
        )
        self.input.installEventFilter(self)

        row = QHBoxLayout()
        self.btn_send = QPushButton("发送")
        self.btn_send.setFixedHeight(30)
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setStyleSheet(
            "QPushButton{background:%s;color:white;border:none;border-radius:6px;}"
            "QPushButton:hover{background:#0C447C;}" % LINE
        )
        self.btn_send.clicked.connect(self.send)
        row.addStretch(1)
        row.addWidget(self.btn_send)

        root.addLayout(bar)
        root.addWidget(self.view, 1)
        root.addWidget(self.input)
        root.addLayout(row)

    # ---------- 字号 ----------
    def apply_font(self, pt):
        """设置里调字号后即时应用到输入框和消息区。"""
        pt = max(9, min(18, int(pt)))
        self._pt = pt
        self.view.setStyleSheet(
            "QTextBrowser{background:#F2F3F5;border:1px solid #D3D1C7;"
            "border-radius:8px;padding:8px;font-size:%dpx;}" % pt
        )
        self.input.setStyleSheet(
            "QPlainTextEdit{background:#F7F9FC;border:1px solid #D3D1C7;"
            "border-radius:8px;padding:6px;font-size:%dpx;}" % pt
        )
        self._render()   # 气泡里的字号也要跟着变

    # ---------- 跟随桌宠 ----------
    def follow(self):
        """把面板摆在桌宠旁边；桌宠移动时重复调用即可跟随。

        优先放桌宠左侧（不挡右边常用的滚动条区域），左边放不下就翻到右侧；
        再整体夹回屏幕可用区内，避免被拖出屏幕找不回来。
        """
        if not self.isVisible() or self.drag:
            return  # 用户正在拖面板本身，别跟他抢
        g = self.pet.frameGeometry()
        scr = QApplication.primaryScreen().availableGeometry()
        x = g.left() - self.width() - 12
        if x < scr.left() + 4:
            x = g.right() + 12
        y = g.bottom() - self.height()
        x = max(scr.left() + 4, min(x, scr.right() - self.width() - 4))
        y = max(scr.top() + 4, min(y, scr.bottom() - self.height() - 4))
        self.move(int(x), int(y))

    # ---------- 气泡接续 ----------
    def continue_bubble(self, bubble_text, image_b64=None):
        """单击气泡后进入：每次都是全新对话框，内容=这轮截图+气泡那句话。"""
        if self.worker:
            return
        import base64

        # 全新会话：清掉之前所有内容
        self.msgs = []
        self.tip.setText("")
        self._ctx_image = image_b64
        self._ctx_text = bubble_text

        # 截图落盘：模型上下文用它；面板里放一条可点击的居中提示
        if image_b64:
            try:
                shot_path = os.path.join(config.BASE_DIR, "last_shot.jpg")
                with open(shot_path, "wb") as f:
                    f.write(base64.b64decode(image_b64.split(",", 1)[1]))
                self._append(
                    "notice",
                    '<a href="file:///%s" style="color:#6E6E6E;text-decoration:none;">'
                    '📎 本轮截图（点击查看）</a>' % shot_path.replace("\\", "/"),
                    notice=True)
            except Exception:
                pass
        self._append("小贾", bubble_text)
        self._cursor_end()
        self.input.setFocus()

    # ---------- 拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 40:
            self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag:
            self.move(e.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, e):
        self.drag = None

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if obj is self.input and e.type() == QEvent.KeyPress:
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                if e.modifiers() & Qt.ShiftModifier:
                    return False          # Shift+Enter：换行，交给控件默认行为
                self.send()               # Enter：发送
                return True
        return super().eventFilter(obj, e)

    # ---------- 对话 ----------
    # 微信式气泡：小贾在左（白底）、你在右（绿底）、系统提示居中灰底。
    # QTextDocument 不支持 inline-block 和圆角，所以用定宽 table 模拟气泡，
    # 宽度按像素估算（中文全宽、ASCII 半宽），超宽自动封顶换行。
    def _bubble_html(self, who, text):
        pt = self._pt
        if who == "notice":
            return ('<div align="center" style="margin:9px 0 2px 0;">'
                    '<span style="background:#DCDEE1;color:#6E6E6E;font-size:%dpx;">'
                    '&nbsp;%s&nbsp;</span></div>' % (max(10, pt - 2), text))
        me = (who == "你")
        max_line, line = 0, 0
        for ch in text:
            if ch == "\n":
                max_line, line = max(max_line, line), 0
            else:
                line += pt if ord(ch) > 0x2E80 else pt * 0.55
        w = max(64, min(300, int(max(max_line, line)) + 26))
        align = "right" if me else "left"
        body = html.escape(text).replace("\n", "<br>") or "&nbsp;"
        return (
            '<div align="%s" style="color:#9AA3AC;font-size:11px;'
            'margin:9px 4px 2px 4px;">%s</div>'
            '<div align="%s"><table width="%d" cellspacing="0" cellpadding="0"><tr>'
            '<td bgcolor="%s" style="padding:7px 9px;">'
            '<span style="color:#2B2B2B;font-size:%dpx;">%s</span>'
            '</td></tr></table></div>'
            % (align, html.escape(who), align, w,
               "#95EC69" if me else "#FFFFFF", pt, body)
        )

    def _render(self):
        if not self.msgs:
            self.view.setHtml(
                '<div style="font-family:Microsoft YaHei;color:#9AA3AC;">'
                '还没有对话。点桌宠的气泡，或直接在下面输入。</div>')
            return
        self.view.setHtml(
            '<div style="font-family:Microsoft YaHei;">%s</div>'
            % "".join(self._bubble_html(w, t) for w, t, _n in self.msgs))
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append(self, who, text, notice=False):
        self.msgs.append((who, text, notice))
        self._render()

    def clear(self):
        """清空对话内容（托盘「清空记忆」调用）。"""
        self.msgs = []
        self._render()

    def _cursor_end(self):
        """滚到底部。"""
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send(self):
        if not self.brain.ready:
            self.tip.setText("先在设置里填 API Key")
            return
        text = self.input.toPlainText().strip()
        if not text or self.worker:
            return
        self.input.clear()
        self.tip.setText("")
        self._append("你", text)
        self._append("小贾", "")
        self._cursor_end()
        self.pet.set_talking(True)
        # 来自气泡的会话：第一条消息自动带上截图和气泡那句话，且不掺历史
        image = self.__dict__.pop("_ctx_image", None)
        ctx = self.__dict__.pop("_ctx_text", "")
        prompt, fresh = text, False
        if image is not None:
            fresh = True
            if ctx:
                prompt = ("（你刚才看了用户的屏幕，说的是「%s」。用户接着这个话题说：）%s\n"
                          "（提示：截图里若出现小贾桌宠的卡通形象——"
                          "猫猫/史莱姆/机器人造型——那是你自己，"
                          "不要对它提问或评论。）") % (ctx, text)
            else:
                prompt = text
        self.worker = StreamWorker(self.brain, prompt, image, fresh=fresh)
        self.worker.delta.connect(self._on_delta)
        self.worker.failed.connect(self._on_fail)
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    # 「看屏幕」「记笔记」功能已移除：带图请求在部分接口上会无响应，
    # 且截屏范围/自身遮挡问题多。保留 brain.grab_screen 供感知使用。

    def _on_delta(self, d):
        # 流式增量续写到最后一个气泡里，整块重渲染（内容短，开销可忽略）
        if self.msgs:
            who, text, notice = self.msgs[-1]
            self.msgs[-1] = (who, text + d, notice)
        self._render()

    def _on_fail(self, msg):
        if self.msgs:
            who, text, notice = self.msgs[-1]
            self.msgs[-1] = (who, text + "（出错：" + msg + "）", notice)
        self._render()
        self.tip.setText("接口出错")
        self._finish()

    def _on_done(self):
        plain = self.msgs[-1][1].strip() if self.msgs else ""
        self._finish()
        self.bubble.say(self.pet, plain[:60] + ("…" if len(plain) > 60 else ""), 8000)

    def _finish(self):
        self.pet.set_talking(False)
        self.worker = None
