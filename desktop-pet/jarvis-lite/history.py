import html
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout,
)

import config
import theme


class History(QDialog):
    """回看它说过的话——只显示它弹出过的内容，简易气泡样式。"""

    def __init__(self, cfg=None):
        super().__init__()
        self._name = ((cfg or config.load()).get("pet") or {}).get("name") or "桌宠"
        self.setWindowTitle("它都说了什么")
        self.resize(600, 580)
        self.setStyleSheet(theme.app_qss())
        self._build()
        self._load_dates()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        row = QHBoxLayout()
        lab = QLabel("日期")
        lab.setStyleSheet("color:%s;" % theme.TEXT_SUB)
        row.addWidget(lab)
        self.combo = QComboBox()
        self.combo.currentTextChanged.connect(self._show)
        row.addWidget(self.combo, 1)
        open_dir = QPushButton("打开文件夹")
        open_dir.setObjectName("ghost")
        open_dir.setCursor(Qt.PointingHandCursor)
        open_dir.clicked.connect(lambda: os.startfile(config.MEMORY_DIR))
        row.addWidget(open_dir)
        root.addLayout(row)

        self.view = QTextBrowser()
        # 微信式观感：浅灰聊天背景，白色气泡浮在上面
        self.view.setStyleSheet(
            "QTextBrowser{background:%s;border:1px solid %s;"
            "border-radius:%dpx;padding:8px;font-size:13px;}"
            % (theme.CARD_ALT, theme.BORDER, theme.RADIUS)
        )
        root.addWidget(self.view, 1)

        close = QPushButton("关闭")
        close.setObjectName("primary")
        close.setMinimumWidth(92)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        root.addWidget(close, alignment=Qt.AlignRight)

    def _load_dates(self):
        days = sorted(
            [f[:-5] for f in os.listdir(config.MEMORY_DIR) if f.endswith(".json")],
            reverse=True,
        )
        if not days:
            self.view.setPlainText("还没有任何记录。")
            return
        self.combo.addItems(days)

    @staticmethod
    def _bubble(ts, text):
        """微信式气泡：昵称+时间灰字在上方，白色气泡宽度随内容自适应。

        QTextDocument 不支持 inline-block/圆角，用定宽 table 模拟；
        文本宽度按像素估算（中文全宽、ASCII 半宽），超宽自动封顶换行。
        """
        line_w = 0
        max_line = 0
        for ch in text:
            if ch == "\n":
                max_line = max(max_line, line_w)
                line_w = 0
            else:
                line_w += 13 if ord(ch) > 0x2E80 else 7
        max_line = max(max_line, line_w)
        w = max(90, min(430, int(max_line) + 28))
        body = html.escape(text).replace("\n", "<br>")
        return (
            '<div style="color:#9AA3AC;font-size:11px;margin:10px 2px 2px 2px;">'
            '%s&nbsp;&nbsp;%s</div>'
            '<table width="%d" cellspacing="0" cellpadding="0"><tr>'
            '<td bgcolor="#FFFFFF" style="padding:7px 9px;">'
            '<span style="color:#2B2B2B;">%s</span></td></tr></table>'
            % (html.escape(self._name), html.escape(ts), w, body))

    def _show(self, day):
        path = os.path.join(config.MEMORY_DIR, day + ".json")
        if not os.path.exists(path):
            return
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            return

        # 只显示它说过的话（assistant），用户输入和内置提示词一律不进历史
        bubbles = []
        for m in reversed(data):  # 最近的在最上面
            if m.get("role") != "assistant":
                continue
            text = (m.get("content") or "").strip()
            if not text or text.startswith("[ERROR]"):
                continue
            bubbles.append(self._bubble(m.get("ts", "--:--"), text))

        self.view.setHtml(
            '<div style="font-family:Microsoft YaHei;">%s</div>'
            % ("".join(bubbles)
               or '<div style="color:#999999;">这一天它没说过话。</div>'))
        self.view.verticalScrollBar().setValue(0)


class Memo(QDialog):
    """长期记忆：它到底记住了关于你的什么。

    原来这里是用 os.startfile 打开 user_memory.md，但 .md 没有文件关联时
    Windows 会静默失败（点菜单没反应），所以改成直接弹窗显示，顺带能编辑。
    """

    def __init__(self, cfg=None):
        super().__init__()
        self._cfg = cfg or config.load()
        self._name = (self._cfg.get("pet") or {}).get("name") or "桌宠"
        self.setWindowTitle("%s记住了什么" % self._name)
        self.resize(560, 520)
        self.setStyleSheet(theme.app_qss())
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        tip = QLabel(
            "这里是它从你们的聊天里慢慢攒下来的、关于你的事实。"
            "每次说话都会带上这些，所以它越用越懂你。\n"
            "可以直接在这里改，改完点「保存」。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:%s;font-size:11px;" % theme.TEXT_SUB)
        root.addWidget(tip)

        self.edit = QPlainTextEdit()
        self.edit.setPlainText(self._read())
        self.edit.setPlaceholderText(
            "还是空的——多聊几次，它就会开始记住关于你的事了。")
        root.addWidget(self.edit, 1)

        row = QHBoxLayout()
        path_tip = QLabel("存于 user_memory.md")
        path_tip.setStyleSheet("color:%s;font-size:11px;" % theme.TEXT_SUB)
        row.addWidget(path_tip)
        row.addStretch(1)

        clear = QPushButton("全部清空")
        clear.setObjectName("ghost")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear)
        row.addWidget(clear)

        close = QPushButton("关闭")
        close.setObjectName("ghost")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        row.addWidget(close)

        save = QPushButton("保存")
        save.setObjectName("primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save)
        row.addWidget(save)
        root.addLayout(row)

    @staticmethod
    def _read():
        try:
            with open(config.USER_MEMO_PATH, encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _write(self, text):
        text = (text or "").strip()
        try:
            with open(config.USER_MEMO_PATH, "w", encoding="utf-8") as f:
                f.write(text + "\n" if text else "")
            return True
        except Exception as e:
            QMessageBox.warning(self, "存不下来", str(e)[:150])
            return False

    def _save(self):
        if self._write(self.edit.toPlainText()):
            self.accept()

    def _clear(self):
        ans = QMessageBox.question(
            self, "确认清空",
            "清空它对你的全部长期记忆？\n（对话记录不受影响）")
        if ans == QMessageBox.Yes:
            self.edit.setPlainText("")
            self._save()
