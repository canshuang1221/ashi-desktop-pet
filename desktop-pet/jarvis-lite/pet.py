import math
import os
import time
from datetime import datetime

import config

from PySide6.QtCore import (
    QEasingCurve, QPoint, QRect, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient,
    QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

BODY = "#DCE7F5"
LINE = "#185FA5"
MASK = "#0C447C"
EYE = "#5DCAA5"
SPARK = "#EF9F27"
DOCK_TH = 0    # 完全贴住屏幕边缘（0 = 刚好贴上）才停靠；负值需略微超出
# 小球绘制在 W×H 画布中间：身体横向从 BODY_L 到 BODY_R，两侧是透明边距。
# 停靠露出的宽度必须大于透明边距，否则露出来的是一片空白，看着像「桌宠消失了」。
BODY_L, BODY_R = 31, 119
PEEK = 20      # 停靠时额外露出多少「身体」


def edge_visible(scale=1.0):
    """停靠时应露出的宽度：透明边距 + 一点身体，随缩放变化。"""
    return max(34, int((Pet.W - BODY_R + PEEK) * scale))


class Pet(QWidget):
    """桌面常驻桌宠：可拖动、置顶、呼吸浮动、会眨眼。"""

    # 位置变化时发出，让气泡 / 对话面板跟着走
    moved = Signal()

    W, H = 150, 180

    def __init__(self, cfg, on_action):
        super().__init__()
        self.cfg = cfg
        self.on_action = on_action
        self.t0 = time.time()
        self.talking = False
        self.sensing = True
        self.drag = None
        self._blink_at = time.time() + 3
        self._blink_until = 0
        self._s = float(cfg["pet"].get("scale", 1.0))
        self._skin = cfg["pet"].get("skin", "cat")
        self._dock_side = None    # None / "left" / "right" / "top"
        self._home = None         # 未停靠时的完整位置
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.move(v))

        self.setWindowTitle("JarvisLite")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(int(self.W * self._s), int(self.H * self._s))
        self._restore_pos()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(40)

    def apply_scale(self, s):
        """设置里改了缩放立即生效，不用重启。"""
        self._s = max(0.4, min(2.5, float(s)))
        self.setFixedSize(int(self.W * self._s), int(self.H * self._s))
        if self._dock_side and self._home is not None:
            self.move(self._dock_target(self._dock_side))
        self.update()

    # ---------- 位置 ----------
    def _restore_pos(self):
        scr = QApplication.primaryScreen().availableGeometry()
        x, y = self.cfg["pet"]["x"], self.cfg["pet"]["y"]
        if x < 0 or y < 0:
            x = scr.right() - self.width() - 40
            y = scr.bottom() - self.height() - 60
        self._home = QPoint(int(x), int(y))
        self.move(self._home)
        side = self._edge_check(self._home)
        if side:
            self._dock_side = side
            self.move(self._dock_target(side))

    def _edge_check(self, pos):
        """松手位置贴近哪条屏幕边（可用区域内）。"""
        scr = QApplication.primaryScreen().availableGeometry()
        if pos.x() + self.width() >= scr.right() - DOCK_TH:
            return "right"
        if pos.x() <= scr.left() + DOCK_TH:
            return "left"
        if pos.y() <= scr.top() + DOCK_TH:
            return "top"
        return None

    def reset_pos(self):
        """回到右下角完整可见位置并取消停靠——靠边藏起来找不到时用。"""
        scr = QApplication.primaryScreen().availableGeometry()
        self._anim.stop()
        self._dock_side = None
        self._home = QPoint(
            scr.right() - self.width() - 60,
            scr.bottom() - self.height() - 80,
        )
        self.move(self._home)
        self.save_pos()

    def _dock_target(self, side):
        scr = QApplication.primaryScreen().availableGeometry()
        e = edge_visible(self._s)
        if side == "left":
            return QPoint(scr.left() - self.width() + e, self._home.y())
        if side == "right":
            return QPoint(scr.right() - e, self._home.y())
        return QPoint(self._home.x(), scr.top() - self.height() + e)

    def _slide(self, target):
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(target)
        self._anim.start()

    def moveEvent(self, e):
        """位置一变就通知气泡 / 对话面板跟随。

        拖动是逐帧 move，停靠也是 QVariantAnimation 逐帧 move，
        都会走到这里，所以气泡能一路贴着桌宠走。
        """
        super().moveEvent(e)
        self.moved.emit()

    def save_pos(self):
        pos = self._home if self._home is not None else self.pos()
        self.cfg["pet"]["x"] = pos.x()
        self.cfg["pet"]["y"] = pos.y()

    # ---------- 交互 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._anim.stop()
            if self._dock_side and self._home is not None:
                # 从停靠状态拖出来：先瞬间回到完整位置，再开始拖
                self.move(self._home)
            self._press_pos = e.globalPosition().toPoint()
            self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self.drag:
            self.move(e.globalPosition().toPoint() - self.drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.drag:
            self.drag = None
            self._home = self.pos()
            side = self._edge_check(self.pos())
            self._dock_side = side
            if side:
                self._slide(self._dock_target(side))
            # 关键修复：之前只在「不靠边」分支才 save_pos，导致用户拖到屏幕边缘
            # 停靠后配置里的 x/y 永远是上次的旧值，下次重启瞬移回老位置，体验诡异。
            # 现在无脑保存当前位置——下次启动就在用户最后停下的地方。
            self.save_pos()
            self.on_action("save", None)

    def mouseDoubleClickEvent(self, e):
        self.on_action("toggle_sense", None)

    def contextMenuEvent(self, e):
        # QContextMenuEvent 没有 globalPosition()（那是 QMouseEvent 的），
        # 用光标位置更稳，也符合「菜单出现在鼠标处」的预期。
        self.on_action("menu", QCursor.pos())

    def enterEvent(self, e):
        self.setCursor(Qt.PointingHandCursor)
        if self._dock_side and self._home is not None and not self.drag:
            self._slide(self._home)  # 鼠标靠上去就滑出来

    def leaveEvent(self, e):
        if self._dock_side and self._home is not None and not self.drag:
            # 不立刻缩回：鼠标可能正停在宠物与屏幕边缘的缝隙上，
            # 立刻缩回会 enter/leave 交替、左右横跳。延迟后确认真的离开才缩。
            QTimer.singleShot(500, self._maybe_dock_back)

    def _maybe_dock_back(self):
        """缩回前的二次确认：鼠标还在宠物上（含外扩范围）或贴着边缘缝隙就不缩。"""
        if not (self._dock_side and self._home is not None) or self.drag:
            return
        if self.underMouse():
            return
        m = QCursor.pos()
        scr = QApplication.primaryScreen().availableGeometry()
        near_edge = False
        if self._dock_side == "right":
            near_edge = m.x() >= scr.right() - 10
        elif self._dock_side == "left":
            near_edge = m.x() <= scr.left() + 10
        elif self._dock_side == "top":
            near_edge = m.y() <= scr.top() + 10
        if near_edge:
            return  # 鼠标停在缝隙上：保持展开，别横跳
        r = self.frameGeometry().adjusted(-8, -8, 8, 8)  # 交互范围外扩 8px
        if r.contains(m):
            return
        self._slide(self._dock_target(self._dock_side))

    # ---------- 外观 ----------
    SKINS = ("cat", "slime", "robot")
    GLOW_RGB = {"robot": (93, 202, 165), "cat": (246, 185, 196), "slime": (93, 202, 165)}

    def set_talking(self, v):
        self.talking = v

    def set_skin(self, skin):
        """换形象：cat / slime / robot。"""
        if skin in self.SKINS and skin != self._skin:
            self._skin = skin
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(self._s, self._s)
        t = time.time() - self.t0
        bob = math.sin(t * 1.7) * 4.5          # 呼吸浮动
        cx = self.W / 2
        cy = 92 + bob
        now = time.time()
        if now > self._blink_at:
            self._blink_until = now + 0.13
            self._blink_at = now + 2.5 + (now % 3)
        blinking = now < self._blink_until
        gr, gg, gb = self.GLOW_RGB.get(self._skin, self.GLOW_RGB["robot"])
        glow_c = QColor(gr, gg, gb)

        # ---- 地面投影：浮起来时变小变淡 ----
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 30, 45, max(14, 34 - int(bob * 3))))
        p.drawEllipse(QPoint(int(cx), 170), int(32 - bob * 1.1), 6)

        # ---- 说话时的外发光 ----
        if self.talking:
            for i in (3, 2, 1):
                p.setBrush(QColor(gr, gg, gb, 12 * i))
                p.drawEllipse(QPoint(int(cx), int(cy)), 58 + i * 7, 62 + i * 7)

        # ---- 感知中的旋转光环（两段对称弧）----
        if self.sensing:
            p.setBrush(Qt.NoBrush)
            pen = QPen(QColor(gr, gg, gb, 90), 2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            a0 = int(t * 40) % 360
            for off in (0, 180):
                p.drawArc(int(cx - 54), int(cy - 56), 108, 112,
                          (a0 + off) * 16, 70 * 16)
            p.setPen(Qt.NoPen)

        # ---- 按形象分发 ----
        if self._skin == "cat":
            self._draw_cat(p, cx, cy, t, blinking)
        elif self._skin == "slime":
            self._draw_slime(p, cx, cy, t)
        else:
            self._draw_robot(p, cx, cy, t, glow_c, blinking)

        # ---- 底部状态点（感知中带呼吸光）----
        dot = QColor(EYE) if self.sensing else QColor("#9A998F")
        p.setBrush(QColor(dot.red(), dot.green(), dot.blue(), 60))
        p.drawEllipse(QPoint(int(cx + 44), 168), 7, 7)
        p.setBrush(dot)
        p.drawEllipse(QPoint(int(cx + 44), 168), 3, 3)
        p.end()

    # ---------- 猫猫 ----------
    def _draw_cat(self, p, cx, cy, t, blinking):
        sway = math.sin(t * 2.6)

        # 尾巴：从身侧伸出，末端摆动
        tail = QPainterPath()
        tail.moveTo(cx + 34, cy + 30)
        tail.quadTo(cx + 64, cy + 20 + sway * 5, cx + 50 + sway * 6, cy - 8)
        p.setPen(QPen(QColor("#E4D9C3"), 12))
        p.drawPath(tail)
        p.setPen(QPen(QColor("#F7F1E3"), 8))
        p.drawPath(tail)

        # 耳朵（随呼吸轻动）
        ear_tip = 2 + math.sin(t * 1.7) * 1.5
        for side in (-1, 1):
            ear = QPainterPath()
            ex = cx + side * 26
            ear.moveTo(ex - 13, cy - 36)
            ear.lineTo(ex, cy - 62 - ear_tip * side)
            ear.lineTo(ex + 13, cy - 34)
            ear.closeSubpath()
            p.setPen(QPen(QColor("#D8CDB8"), 1.2))
            p.setBrush(QColor("#F7F1E3"))
            p.drawPath(ear)
            inner = QPainterPath()
            inner.moveTo(ex - 6, cy - 38)
            inner.lineTo(ex, cy - 53 - ear_tip * side)
            inner.lineTo(ex + 6, cy - 37)
            inner.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#F6B9C4"))
            p.drawPath(inner)

        # 身体：奶油白渐变
        body = QRadialGradient(cx - 16, cy - 30, 6)
        body.setColorAt(0.0, QColor("#FFFDF6"))
        body.setColorAt(0.6, QColor("#F7F1E3"))
        body.setColorAt(1.0, QColor("#E7DCC5"))
        p.setPen(QPen(QColor("#D8CDB8"), 1.2))
        p.setBrush(QBrush(body))
        p.drawEllipse(int(cx - 42), int(cy - 44), 84, 92)

        # 眼睛（大圆黑眼 + 高光）
        p.setPen(Qt.NoPen)
        if self.talking:
            p.setBrush(QColor("#4A4238"))
            p.drawEllipse(QPoint(int(cx - 15), int(cy - 8)), 6, 7)
            p.drawEllipse(QPoint(int(cx + 15), int(cy - 8)), 6, 7)
        elif blinking:
            p.setPen(QPen(QColor("#4A4238"), 3))
            p.drawLine(int(cx - 21), int(cy - 8), int(cx - 9), int(cy - 8))
            p.drawLine(int(cx + 9), int(cy - 8), int(cx + 21), int(cy - 8))
            p.setPen(Qt.NoPen)
        else:
            for ex in (cx - 15, cx + 15):
                p.setBrush(QColor("#4A4238"))
                p.drawEllipse(QPoint(int(ex), int(cy - 8)), 6.5, 7.5)
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(QPoint(int(ex) - 2, int(cy - 11)), 2, 2)

        # 腮红
        p.setBrush(QColor(246, 185, 196, 150))
        p.drawEllipse(QPoint(int(cx - 26), int(cy + 2)), 8, 5)
        p.drawEllipse(QPoint(int(cx + 26), int(cy + 2)), 8, 5)

        # 嘴：ω 形；说话时张嘴
        p.setPen(QPen(QColor("#8A7A63"), 2))
        p.setBrush(Qt.NoBrush)
        if self.talking:
            p.setBrush(QColor("#D98A94"))
            p.drawEllipse(QPoint(int(cx), int(cy + 6)), 6, 4 + math.sin(t * 9) * 1.5)
        else:
            m = QPainterPath()
            m.moveTo(cx - 6, cy + 3)
            m.quadTo(cx - 3, cy + 7, cx, cy + 3)
            m.quadTo(cx + 3, cy + 7, cx + 6, cy + 3)
            p.drawPath(m)

        # 胡须
        p.setPen(QPen(QColor(180, 168, 140, 170), 1.4))
        for side in (-1, 1):
            for dy in (-3, 2):
                p.drawLine(int(cx + side * 30), int(cy + 2 + dy),
                           int(cx + side * 44), int(cy + dy))

    # ---------- 史莱姆 ----------
    def _draw_slime(self, p, cx, cy, t):
        # 果冻感：宽窄交替的挤压伸展
        squash = math.sin(t * 2.2)
        w = 84 + squash * 4
        h = 92 - squash * 6
        top = cy - h / 2 + 6

        body = QRadialGradient(cx - 14, cy - 26, 6)
        body.setColorAt(0.0, QColor(214, 247, 234, 235))
        body.setColorAt(0.55, QColor(93, 202, 165, 225))
        body.setColorAt(1.0, QColor(52, 168, 130, 225))
        p.setPen(QPen(QColor(40, 140, 105, 200), 1.2))
        p.setBrush(QBrush(body))
        # 底宽顶圆的果冻形
        path = QPainterPath()
        path.moveTo(cx - w / 2, cy + 40)
        path.cubicTo(cx - w / 2 - 2, cy - h / 2, cx + w / 2 + 2, cy - h / 2, cx + w / 2, cy + 40)
        path.closeSubpath()
        p.drawPath(path)

        # 顶部高光 + 底部一滩
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 130))
        p.drawEllipse(QPoint(int(cx - 14), int(top + 14)), 13, 7)
        p.setBrush(QColor(93, 202, 165, 70))
        p.drawEllipse(QPoint(int(cx), int(cy + 46)), int(w / 2 + 6), 6)

        # 眼睛：黑豆眼 + 高光；说话时眯成弧
        if self.talking:
            p.setBrush(QColor("#2E4A42"))
            mw = 4 + abs(math.sin(t * 9)) * 2
            p.drawEllipse(QPoint(int(cx - 14), int(cy - 6)), 6, mw)
            p.drawEllipse(QPoint(int(cx + 14), int(cy - 6)), 6, mw)
        else:
            for ex in (cx - 14, cx + 14):
                p.setBrush(QColor("#2E4A42"))
                p.drawEllipse(QPoint(int(ex), int(cy - 6)), 6, 9)
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(QPoint(int(ex) - 2, int(cy - 10)), 2, 2)
        # 小嘴
        p.setPen(QPen(QColor("#2E4A42"), 2))
        p.setBrush(Qt.NoBrush)
        if self.talking:
            p.setBrush(QColor("#2E4A42"))
            p.drawEllipse(QPoint(int(cx), int(cy + 10)), 5, 3 + abs(math.sin(t * 9)) * 2)
        else:
            m = QPainterPath()
            m.moveTo(cx - 5, cy + 9)
            m.quadTo(cx, cy + 13, cx + 5, cy + 9)
            p.drawPath(m)
            p.setPen(Qt.NoPen)

    # ---------- 机器人（原版）----------
    def _draw_robot(self, p, cx, cy, t, glow_c, blinking):
        # 天线：略带弧度 + 顶端呼吸光点
        ant = QPainterPath()
        ant.moveTo(cx, cy - 46)
        ant.quadTo(cx + 5, cy - 60, cx, cy - 76)
        p.setPen(QPen(QColor("#7FA8D0"), 2))
        p.drawPath(ant)
        pulse = 4.6 + (math.sin(t * 6) * 1.1 if self.talking else math.sin(t * 1.6) * 0.5)
        p.setBrush(QColor(93, 202, 165, 55))
        p.drawEllipse(QPoint(int(cx), int(cy - 79)), int(pulse + 5), int(pulse + 5))
        p.setBrush(QColor(SPARK if self.talking else glow_c))
        p.drawEllipse(QPoint(int(cx), int(cy - 79)), int(pulse), int(pulse))

        # 身体：径向渐变蛋形
        body = QRadialGradient(cx - 18, cy - 42, 6)
        body.setColorAt(0.0, QColor("#FFFFFF"))
        body.setColorAt(0.32, QColor("#E9F3FD"))
        body.setColorAt(0.78, QColor("#C3D9F1"))
        body.setColorAt(1.0, QColor("#A5C2E0"))
        p.setPen(QPen(QColor("#7FA8D0"), 1.2))
        p.setBrush(QBrush(body))
        p.drawEllipse(int(cx - 43), int(cy - 49), 86, 98)

        # 顶部高光
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawEllipse(QPoint(int(cx - 16), int(cy - 34)), 15, 9)

        # 面罩：深色渐变 + 一道高光弧
        visor = QLinearGradient(cx, cy - 32, cx, cy + 16)
        visor.setColorAt(0.0, QColor("#1B4675"))
        visor.setColorAt(1.0, QColor("#0A2647"))
        p.setPen(QPen(QColor("#2E6394"), 1))
        p.setBrush(QBrush(visor))
        p.drawRoundedRect(int(cx - 34), int(cy - 31), 68, 47, 21, 21)
        hl = QPainterPath()
        hl.moveTo(cx - 26, cy - 16)
        hl.quadTo(cx - 12, cy - 28, cx + 4, cy - 26)
        p.setPen(QPen(QColor(255, 255, 255, 55), 2.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(hl)
        p.setPen(Qt.NoPen)

        if self.talking:
            for i in range(5):
                h = 5 + abs(math.sin(t * 9 + i * 0.9)) * 13
                g = QLinearGradient(0, cy - 18 - h / 2, 0, cy - 18 + h / 2)
                g.setColorAt(0.0, QColor("#BFF0DF"))
                g.setColorAt(1.0, QColor(EYE))
                p.setBrush(QBrush(g))
                p.drawRoundedRect(int(cx - 23 + i * 11), int(cy - 18 - h / 2), 6, int(h), 3, 3)
        elif blinking:
            p.setBrush(QColor(EYE))
            p.drawRoundedRect(int(cx - 25), int(cy - 11), 21, 3, 2, 2)
            p.drawRoundedRect(int(cx + 4), int(cy - 11), 21, 3, 2, 2)
        else:
            for ex in (cx - 14, cx + 14):
                p.setBrush(QColor(93, 202, 165, 70))
                p.drawEllipse(QPoint(int(ex), int(cy - 9)), 11, 12)
                p.setBrush(QColor(EYE))
                p.drawEllipse(QPoint(int(ex), int(cy - 9)), 7, 8)
                p.setBrush(QColor(255, 255, 255, 210))
                p.drawEllipse(QPoint(int(ex) - 2, int(cy - 12)), 2, 2)


class Bubble(QWidget):
    """桌宠气泡，自动换行、自动消失。

    主动搭话的气泡是「可双击」的：鼠标悬停在气泡上时暂停自动消失，
    双击气泡触发 open_cb(截图, 气泡文本)，打开对话面板继续聊这个话题。
    """

    def __init__(self, cfg=None, open_cb=None):
        super().__init__()
        self.cfg = cfg or {}
        self.open_cb = open_cb
        self.text = ""
        self._pt = 12
        self.maxw = 260
        self._image = None      # 产生这句话时的截图（可继续聊）
        self._clickable = False
        self._ms = 6000         # 本次气泡应停留的时长
        self._remain = 0        # 悬停暂停时的剩余时长
        self._pet = None        # 绑定桌宠后，桌宠一动气泡就跟着走
        self._h = 0
        self._avoid = []        # 需要避让的窗口（如对话面板），别压在它上面
        self.M = 14             # 四周留白：给指向桌宠的箭头留出绘制空间，否则会被裁掉
        self._body_h = 0        # 气泡本体高度（不含留白）
        # 去掉 WindowTransparentForInput：气泡要能接收鼠标事件
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def _ui(self):
        ui = self.cfg.get("ui", {})
        return (
            max(9, min(18, int(ui.get("font_size", 12)))),
            max(180, min(420, int(ui.get("bubble_width", 260)))),
        )

    def say(self, pet, text, ms=6000, image=None, clickable=False):
        # 每次弹气泡都留痕（毫秒级），方便排查「连弹两个」这类时序问题
        try:
            with open(os.path.join(config.BASE_DIR, "log.txt"), "a", encoding="utf-8") as f:
                f.write("%s [bubble]%s %s\n" % (
                    datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    " [hover]" if clickable else "",
                    text[:60].replace("\n", " ")))
        except Exception:
            pass
        self.text = text
        self._image = image
        self._clickable = clickable and self.open_cb is not None
        self._pt, self.maxw = self._ui()
        # 正式说话的气泡（>=5s）留存时间跟随设置里的「气泡留存」
        if ms >= 5000:
            ms = int(self.cfg.get("ui", {}).get("bubble_ms", ms))
        font = QFont("Microsoft YaHei", self._pt)
        fm = QFontMetrics(font)
        lh = fm.height() + 4
        lines = []
        cur = ""
        for ch in text:
            if fm.horizontalAdvance(cur + ch) > self.maxw - 24:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
        self.lines = lines
        h = 14 + len(lines) * lh
        self._h = h
        self._body_h = h
        self.setFixedSize(self.maxw + 2 * self.M, h + 2 * self.M)
        self._pet = pet
        self._place()
        self.show()
        self.raise_()
        self.update()
        self._ms = ms
        self._timer.start(ms)

    # ---------- 跟随桌宠 ----------
    def avoid(self, *widgets):
        """登记需要避让的窗口（对话面板等），气泡不会压在它们身上。"""
        self._avoid = [w for w in widgets if w is not None]

    def _avoid_rects(self):
        out = []
        for w in self._avoid:
            try:
                if w.isVisible():
                    out.append(w.frameGeometry())
            except Exception:
                pass
        return out

    def _place(self):
        """按桌宠「当前」位置摆放气泡。

        桌宠移动时重复调用即可跟随——不能只在 say() 里算一次，
        否则拖走桌宠后气泡会孤零零留在原地。

        候选位置按优先级依次试：右上 → 左上 → 右侧 → 左侧，
        取第一个「既在屏幕内、又不压住对话面板」的位置。
        """
        pet = self._pet
        if pet is None:
            return
        g = pet.frameGeometry()
        scr = QApplication.primaryScreen().availableGeometry()
        m = self.M
        bw, bh = self.width(), self.height()        # 窗口尺寸（含四周留白）
        bodyW = self.maxw
        bodyH = self._body_h or (bh - 2 * m)
        # 候选位先按「气泡本体」算，再整体减掉留白换算成窗口位置
        cands = (
            (g.right() - 20, g.top() - bodyH - 12),            # 桌宠右上
            (g.left() - bodyW + 20, g.top() - bodyH - 12),     # 桌宠左上
            (g.right() + 6, g.top() + 8),                      # 桌宠右侧
            (g.left() - bodyW - 6, g.top() + 8),               # 桌宠左侧
        )
        cands = [(x - m, y - m) for x, y in cands]
        blockers = self._avoid_rects()

        def _fit(x, y):
            return (max(4, min(int(x), scr.right() - bw - 4)),
                    max(4, min(int(y), scr.bottom() - bh - 4)))

        best = None
        best_pen = None
        for cx, cy in cands:
            x, y = _fit(cx, cy)
            r = QRect(x, y, bw, bh)
            pen = 0
            for b in blockers:
                o = r.intersected(b)
                pen += max(0, o.width()) * max(0, o.height())
            if pen == 0:
                best = (x, y)
                break
            if best_pen is None or pen < best_pen:
                best_pen, best = pen, (x, y)
        if best is None:
            best = _fit(*cands[0])   # 兜底：至少别飞出屏幕
        self.move(best[0], best[1])

    def follow(self):
        """桌宠动了：气泡若可见就跟着挪。"""
        if self.isVisible():
            self._place()

    # ---------- 悬停不消失，单击继续对话 ----------
    def mousePressEvent(self, e):
        """单击气泡：带着截图+这句话的上下文打开对话。"""
        self._open()

    def enterEvent(self, e):
        if self._clickable and self.isVisible():
            self._remain = self._timer.remainingTime()
            self._timer.stop()  # 鼠标在气泡上就别消失

    def leaveEvent(self, e):
        if self._clickable and self.isVisible():
            # 移开后按剩余时长继续倒数（至少再留 1.5 秒）
            self._timer.start(max(1500, self._remain or self._ms))

    def mouseDoubleClickEvent(self, e):
        self._open()  # 双击同样有效（用户手快连点两下时别落空）

    def _open(self):
        if not (self._clickable and self.isVisible()):
            return
        self._timer.stop()
        text, image = self.text, self._image
        self.hide()
        self.open_cb(image, text)

    def _tail_path(self):
        """算出指向桌宠的小箭头（本体局部坐标，已含留白偏移）。

        箭头方向必须跟着桌宠的方位走：气泡落在桌宠右上时朝左下、落在左侧时朝右……
        原来写死在底边（永远朝下），所以一旦气泡和桌宠形成夹角，箭头就指反了。
        """
        m = self.M
        W = self.maxw
        H = self._body_h or (self.height() - 2 * m)
        cx, cy = W / 2.0, H / 2.0
        pet = self._pet
        if pet is None or not pet.isVisible():
            tx, ty = cx, H + 30                      # 没桌宠可指：默认朝下
        else:
            pc = pet.frameGeometry().center()
            tx = pc.x() - self.x() - m               # 换算到本体局部坐标
            ty = pc.y() - self.y() - m
        dx, dy = tx - cx, ty - cy
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            dy = 1.0
        dist = math.hypot(dx, dy)
        ux, uy = dx / dist, dy / dist                # 指向桌宠的单位向量
        hw, hh = W / 2.0, H / 2.0
        kx = hw / abs(ux) if abs(ux) > 1e-6 else float("inf")
        ky = hh / abs(uy) if abs(uy) > 1e-6 else float("inf")
        k = min(kx, ky)
        ax, ay = cx + ux * k, cy + uy * k            # 本体边界上的锚点
        px, py = -uy, ux                             # 垂直于指向的方向
        half = 7.0
        bx, by = ax - ux * 4, ay - uy * 4            # 底边内挪 4px，确保与本体连成一体
        path = QPainterPath()
        path.moveTo(m + bx + px * half, m + by + py * half)
        path.lineTo(m + ax + ux * 11, m + ay + uy * 11)      # 尖端朝桌宠
        path.lineTo(m + bx - px * half, m + by - py * half)
        path.closeSubpath()
        return path

    def paintEvent(self, _):
        if not self.text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = self.M
        W = self.maxw
        H = self._body_h or (self.height() - 2 * m)
        body = QPainterPath()
        body.addRoundedRect(m, m, W, H, 12, 12)
        # 本体与箭头合并成一条轮廓，避免接缝处出现多余描边
        shape = body.united(self._tail_path())
        p.setPen(QPen(QColor(LINE), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(shape)
        p.setPen(QColor("#2C2C2A"))
        p.setFont(QFont("Microsoft YaHei", self._pt))
        lh = QFontMetrics(p.font()).height() + 4
        for i, ln in enumerate(self.lines):
            p.drawText(m + 12, m + 18 + lh * i, ln)
        p.end()
