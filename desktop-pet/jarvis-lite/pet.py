import math
import os
import time
from datetime import datetime

import config

from PySide6.QtCore import (
    QEasingCurve, QPoint, QRect, QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient,
    QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
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
    # 矢量画法的形象。用户反馈简笔画不好看，可选列表只留两个当兜底
    # （立绘素材缺失时用它顶上，保证程序不会画不出来）
    SKINS = ("cat", "slime")

    # ---- 立绘（图片素材）形象 ----
    # 素材放 assets/ 下、PNG 带透明通道，命名 <base>_idle.png / _blink.png / _talk.png。
    # 只有 idle 也能用（其余帧自动退回 idle）；一张都没有时退回第三项指定的矢量画法，
    # 所以素材没到位程序照样能跑，不会崩。
    # 用多帧而不是单张，是为了让有立绘的形象也能眨眼、说话，不至于变成一张静止贴图。
    IMAGE_SKINS = {
        "pic_cat": ("立绘 · 猫耳少女", "pic_cat", "cat"),
        "pic_fox": ("立绘 · 狐耳少女", "pic_fox", "fox"),
        "pic_panda": ("立绘 · 熊猫娘", "pic_panda", "panda"),
        "pic_robot": ("立绘 · 红色机甲", "pic_robot", "robot"),
        "pic_plush": ("立绘 · 毛绒小兽", "pic_plush", "cat"),
    }
    _img_cache = {}

    @classmethod
    def label(cls, skin):
        """形象的中文名（设置面板下拉用）。"""
        if skin in cls.IMAGE_SKINS:
            return cls.IMAGE_SKINS[skin][0]
        return (cls.CHIBI.get(skin) or cls.CHIBI["cat"])["label"]

    @classmethod
    def available(cls):
        """可选形象：矢量画法全部列出；立绘只在素材确实存在时才出现，
        免得用户选到一个空条目。素材随时补进来，重开设置面板即可看到。"""
        out = list(cls.SKINS)
        for k in cls.IMAGE_SKINS:
            if cls._frames(k):
                out.append(k)
        return out

    @classmethod
    def _frames(cls, name):
        """取某套立绘的各帧。只缓存加载成功的，方便用户随时补素材。"""
        cache = cls._img_cache
        got = cache.get(name)
        if got:
            return got
        base = cls.IMAGE_SKINS[name][1]
        out = {}
        for key in ("idle", "blink", "talk"):
            names = ["%s_%s.png" % (base, key)]
            if key == "idle":
                names.append("%s.png" % base)   # 容许只有一张不带后缀的
            found = False
            for fname in names:
                for d in config.ASSETS_DIRS:
                    path = os.path.join(d, fname)
                    if os.path.exists(path):
                        pm = QPixmap(path)
                        if not pm.isNull():
                            out[key] = pm
                            found = True
                            break
                if found:
                    break
        if out:
            cache[name] = out
        return out
    GLOW_RGB = {
        "robot": (93, 202, 165),
        "cat": (246, 185, 196),
        "shiba": (239, 159, 39),
        "panda": (168, 194, 224),
        "slime": (93, 202, 165),
        # 立绘也要给个配色，否则说话外发光和感知光环会走默认的绿色，跟角色不搭
        "pic_cat": (246, 185, 196),
        "pic_fox": (239, 159, 39),
        "pic_panda": (168, 194, 224),
        "pic_robot": (93, 202, 165),
        "pic_plush": (72, 190, 168),      # 取它围巾的青色
    }

    def set_talking(self, v):
        self.talking = v

    def set_skin(self, skin):
        """换形象：cat / shiba / ... / pic_cat（立绘）。

        切换时清掉图片缓存，这样用户刚把 PNG 放进 assets/ 就能立刻生效，
        不必重启程序。
        """
        if (skin in self.SKINS or skin in self.IMAGE_SKINS) and skin != self._skin:
            self._skin = skin
            self.__class__._img_cache.clear()
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

        # ---- 按形象分发（立绘优先，缺图退回矢量）----
        self._draw_pet(p, cx, cy, t, blinking, glow_c)

        # ---- 底部状态点（感知中带呼吸光）----
        dot = QColor(EYE) if self.sensing else QColor("#9A998F")
        p.setBrush(QColor(dot.red(), dot.green(), dot.blue(), 60))
        p.drawEllipse(QPoint(int(cx + 44), 168), 7, 7)
        p.setBrush(dot)
        p.drawEllipse(QPoint(int(cx + 44), 168), 3, 3)
        p.end()

    # ---------- 二次元 Q 版形象 ----------
    # 所有形象共用同一套几何（大头 + 小身体 + 大眼），只换配色与配件，
    # 这样风格统一、加新形象只需往 CHIBI 里加一条。
    # 可爱与否主要靠眼睛：眼白 + 渐变虹膜 + 深瞳 + 双高光 + 上眼睑睫毛 + 腮红。
    CHIBI = {
        "cat": dict(
            label="猫娘", skin="#FFF1E6", hair="#F7B98B", hair_sh="#DD9256",
            eye="#3FA9A0", ear="cat", ear_in="#F9C7D0", acc="ribbon",
            acc_color="#EF8095", tail="cat", blush="#F6A9B8", ahoge=True,
        ),
        "shiba": dict(
            label="柴犬", skin="#F7C98B", hair="#F0B96C", hair_sh="#D0913F",
            eye="#4A4238", ear="dog", ear_in="#FCEBDA", acc=None,
            acc_color=None, tail="curl", blush="#EE9E86", muzzle=True,
        ),
        "fox": dict(
            label="狐娘", skin="#FFF4E9", hair="#F6E7D7", hair_sh="#D9C1A6",
            eye="#E2A03C", ear="fox", ear_in="#F8D6C4", acc=None,
            acc_color=None, tail="fox", blush="#F3BEC0", muzzle=True,
        ),
        "bunny": dict(
            label="兔娘", skin="#FFF3F2", hair="#DCD1F5", hair_sh="#B7A6DE",
            eye="#8E6FD8", ear="bunny", ear_in="#F8CBDB", acc="ribbon",
            acc_color="#9B8CE0", tail="ball", blush="#F2B6C6", ahoge=False,
        ),
        "panda": dict(
            label="熊猫", skin="#FDFDFD", hair="#3C3C3C", hair_sh="#242424",
            eye="#2B2B2B", ear="round", ear_in="#5E5E5E", acc=None,
            acc_color=None, tail="ball", blush="#F3B9C2", panda=True, bare=True,
        ),
        "tiger": dict(
            label="虎娘", skin="#FFDCA6", hair="#F5B65C", hair_sh="#D18F33",
            eye="#3F8A6E", ear="round", ear_in="#F8D2D8", acc=None,
            acc_color=None, tail="tiger", blush="#F2A98F", muzzle=True,
            stripes="#9A6430",
        ),
        "robot": dict(
            label="机娘", skin="#EEF5FF", hair="#A6C9EA", hair_sh="#7BA6D0",
            eye="#5DCAA5", ear="none", ear_in=None, acc="headset",
            acc_color="#5DCAA5", tail=None, blush="#C3DAF5", antenna=True,
        ),
        "slime": dict(
            label="果冻", skin="#B9EED9", hair="#7CD9B8", hair_sh="#4BBE97",
            eye="#2E6E58", ear="none", ear_in=None, acc=None, acc_color=None,
            tail=None, blush="#F6A9B8", jelly=True, bare=True,
        ),
    }

    # ---- 眼睛 ----
    def _chibi_eyes(self, p, cx, hy, spec, blinking, talking, t, half=13.5):
        base = QColor(spec["eye"])
        iris_hi = base.lighter(145).name()
        iris_lo = base.darker(150).name()
        for s in (-1, 1):
            ex, ey = cx + s * half, hy + 7
            if blinking or talking:
                # 眨眼 / 说话：上弯的弧，看着像眯眼笑
                p.setPen(QPen(QColor("#4A4A4A"), 2.4))
                p.setBrush(Qt.NoBrush)
                a = QPainterPath()
                off = 2 if talking else 0
                a.moveTo(ex - 7.5, ey + off)
                a.quadTo(ex, ey - 5.5 + off, ex + 7.5, ey + off)
                p.drawPath(a)
                p.setPen(Qt.NoPen)
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPoint(int(ex), int(ey)), 8, 10)
            g = QLinearGradient(ex, ey - 9, ex, ey + 10)
            g.setColorAt(0.0, QColor(iris_hi))
            g.setColorAt(1.0, QColor(iris_lo))
            p.setBrush(QBrush(g))
            p.drawEllipse(QPoint(int(ex), int(ey + 1)), 6.6, 8.2)
            p.setBrush(QColor("#22303A"))
            p.drawEllipse(QPoint(int(ex), int(ey + 2)), 3.3, 4.8)
            p.setBrush(QColor(255, 255, 255, 245))
            p.drawEllipse(QPoint(int(ex - 2.7), int(ey - 3.8)), 2.7, 3.3)
            p.setBrush(QColor(255, 255, 255, 150))
            p.drawEllipse(QPoint(int(ex + 3.2), int(ey + 4.2)), 1.5, 1.7)
            # 上眼睑（睫毛）与眼角挑线
            p.setPen(QPen(QColor("#3C3C3C"), 2.0))
            p.setBrush(Qt.NoBrush)
            lid = QPainterPath()
            lid.moveTo(ex - 9, ey - 2)
            lid.quadTo(ex, ey - 13, ex + 9, ey - 2)
            p.drawPath(lid)
            p.drawLine(int(ex + s * 8), int(ey - 4), int(ex + s * 12.5), int(ey - 8))
            p.setPen(Qt.NoPen)

    # ---- 耳朵 ----
    def _chibi_ears(self, p, cx, hy, r, t, spec, sway):
        kind = spec["ear"]
        if not kind or kind == "none":
            return
        inner = QColor(spec["ear_in"]) if spec["ear_in"] else QColor(spec["hair_sh"])
        for s in (-1, 1):
            ex = cx + s * (r * 0.62)
            base_y = hy - r * 0.62
            if kind == "cat":
                h, w = 30, 15
                outer = [(ex - w / 2, base_y + 8), (ex + s * 3, base_y - h), (ex + w / 2, base_y + 6)]
            elif kind == "fox":
                h, w = 38, 18
                outer = [(ex - w / 2, base_y + 10), (ex + s * 4, base_y - h), (ex + w / 2 + s * 4, base_y + 6)]
            elif kind == "dog":
                h, w = 24, 19
                outer = [(ex - w / 2, base_y + 4), (ex + s * 2, base_y - h), (ex + w / 2 + s * 5, base_y + 10)]
            elif kind == "bunny":
                h, w = 44, 15
                outer = [(ex - w / 2, base_y + 6), (ex + s * 6, base_y - h), (ex + w / 2 + s * 2, base_y + 4)]
            else:  # round：熊猫 / 老虎那种圆耳
                h, w = 17, 17
                outer = None
            if outer is None:
                p.setPen(QPen(QColor(spec["hair_sh"]), 1.2))
                p.setBrush(QColor(spec["hair"]))
                p.drawEllipse(QPoint(int(ex), int(base_y - 4)), int(w / 2 + 3), int(h / 2 + 3))
                p.setPen(Qt.NoPen)
                p.setBrush(inner)
                p.drawEllipse(QPoint(int(ex), int(base_y - 3)), int(w / 4 + 2), int(h / 4 + 2))
                continue
            ear = QPainterPath()
            ear.moveTo(*outer[0])
            ear.quadTo(ex + s * 2, base_y - h - 6, outer[1][0], outer[1][1])
            ear.quadTo(ex + s * 6, base_y - 4, outer[2][0], outer[2][1])
            ear.closeSubpath()
            p.setPen(QPen(QColor(spec["hair_sh"]), 1.2))
            p.setBrush(QColor(spec["hair"]))
            p.drawPath(ear)
            # 耳朵内侧
            inner_p = QPainterPath()
            inner_p.moveTo(ex - w * 0.26, base_y + 2)
            inner_p.quadTo(ex + s * 1.5, base_y - h * 0.62, ex + w * 0.24, base_y + 1)
            inner_p.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(inner)
            p.drawPath(inner_p)

    # ---- 头发（含刘海与呆毛）----
    def _chibi_hair(self, p, cx, hy, r, t, spec, sway):
        # 熊猫 / 果冻这类本来就没头发的形象：只在头顶加一道柔和高光，别盖成头盔
        if spec.get("bare"):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 95))
            hl = QPainterPath()
            hl.moveTo(cx - r * 0.55, hy - r * 0.42)
            hl.quadTo(cx, hy - r * 0.98, cx + r * 0.55, hy - r * 0.42)
            hl.quadTo(cx, hy - r * 0.68, cx - r * 0.55, hy - r * 0.42)
            p.drawPath(hl)
            return
        R = r + 2
        hair = QPainterPath()
        hair.moveTo(cx - R, hy + 1)
        hair.arcTo(QRectF(cx - R, hy - R, 2 * R, 2 * R), 180, -180)
        # 从右到左压出三缕刘海。下缘抬到额头位置——原来压到 hy+2 太低，
        # 整个头被包住，看着像戴了顶帽子。
        hair.quadTo(cx + R * 0.62, hy + 15, cx + R * 0.28, hy - 4)
        hair.quadTo(cx, hy + 17, cx - R * 0.28, hy - 4)
        hair.quadTo(cx - R * 0.62, hy + 15, cx - R, hy + 1)
        hair.closeSubpath()
        p.setPen(QPen(QColor(spec["hair_sh"]), 1.2))
        p.setBrush(QColor(spec["hair"]))
        p.drawPath(hair)
        # 两侧垂发（贴着脸，增加层次）
        p.setBrush(QColor(spec["hair"]))
        for s in (-1, 1):
            side = QPainterPath()
            x = cx + s * (r - 1)
            side.moveTo(x, hy - 9)
            side.quadTo(x + s * 11, hy + 9, x + s * 2, hy + 27)
            side.quadTo(x - s * 5, hy + 9, x, hy - 9)
            p.drawPath(side)
        # 发丝高光
        p.setPen(QPen(QColor(255, 255, 255, 110), 2.4))
        p.setBrush(Qt.NoBrush)
        hl = QPainterPath()
        hl.moveTo(cx - r * 0.65, hy - r * 0.42)
        hl.quadTo(cx - r * 0.1, hy - r * 0.86, cx + r * 0.52, hy - r * 0.5)
        p.drawPath(hl)
        p.setPen(Qt.NoPen)
        # 呆毛
        if spec.get("ahoge"):
            a = QPainterPath()
            a.moveTo(cx - 3, hy - R + 2)
            a.quadTo(cx + 6 + sway * 4, hy - R - 14, cx + 20 + sway * 6, hy - R - 6)
            p.setPen(QPen(QColor(spec["hair"]), 2.6))
            p.setBrush(Qt.NoBrush)
            p.drawPath(a)
            p.setPen(Qt.NoPen)

    # ---- 嘴 / 鼻 ----
    def _chibi_mouth(self, p, cx, hy, spec, t):
        my = hy + 21
        p.setPen(QPen(QColor("#4A4A4A"), 1.8))
        p.setBrush(Qt.NoBrush)
        if self.talking:
            p.setBrush(QColor("#E08B95"))
            p.setPen(QPen(QColor("#C9707B"), 1.4))
            p.drawEllipse(QPoint(int(cx), int(my + 1)), 4.2, 3 + abs(math.sin(t * 9)) * 2.2)
            p.setPen(Qt.NoPen)
            return
        if spec.get("muzzle"):
            # 犬科/虎：小鼻头 + ω 嘴
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#5A4A44"))
            nose = QPainterPath()
            nose.moveTo(cx - 3.6, my - 5)
            nose.quadTo(cx, my - 8.6, cx + 3.6, my - 5)
            nose.quadTo(cx, my - 1.6, cx - 3.6, my - 5)
            p.drawPath(nose)
            p.setPen(QPen(QColor("#4A4A4A"), 1.6))
            p.setBrush(Qt.NoBrush)
            m = QPainterPath()
            m.moveTo(cx - 6, my - 1)
            m.quadTo(cx - 3, my + 3.4, cx, my - 0.4)
            m.quadTo(cx + 3, my + 3.4, cx + 6, my - 1)
            p.drawPath(m)
            p.setPen(Qt.NoPen)
            return
        m = QPainterPath()
        m.moveTo(cx - 4.5, my - 2)
        m.quadTo(cx, my + 2.6, cx + 4.5, my - 2)
        p.drawPath(m)

    # ---- 配件：发带 / 耳机 / 天线 ----
    def _chibi_acc(self, p, cx, hy, r, t, spec, glow_c):
        acc = spec.get("acc")
        if acc == "ribbon":
            rx, ry = cx - r * 0.72, hy - r * 0.66
            col = QColor(spec["acc_color"])
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            for s in (-1, 1):
                rp = QPainterPath()
                rp.moveTo(rx, ry)
                rp.quadTo(rx + s * 11, ry - 8, rx + s * 13, ry + 3)
                rp.quadTo(rx + s * 6, ry + 4, rx, ry)
                p.drawPath(rp)
            p.setBrush(col.lighter(115))
            p.drawEllipse(QPoint(int(rx), int(ry)), 3.4, 3.4)
        elif acc == "headset":
            col = QColor(spec["acc_color"])
            p.setPen(QPen(QColor(spec["hair_sh"]), 3.2))
            p.setBrush(Qt.NoBrush)
            band = QPainterPath()
            band.moveTo(cx - r * 0.95, hy - 2)
            band.arcTo(QRectF(cx - r - 4, hy - r - 8, 2 * (r + 4), 2 * (r + 4)), 175, -170)
            p.drawPath(band)
            p.setPen(QPen(QColor("#5B7FA6"), 1.2))
            p.setBrush(col)
            for s in (-1, 1):
                p.drawRoundedRect(int(cx + s * r - (7 if s > 0 else 1)), int(hy - 8), 8, 15, 3, 3)
            p.setPen(Qt.NoPen)
        if spec.get("antenna"):
            ant = QPainterPath()
            ant.moveTo(cx, hy - r - 1)
            ant.quadTo(cx + 5, hy - r - 14, cx + 1, hy - r - 24)
            p.setPen(QPen(QColor("#8FB6DC"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(ant)
            pulse = 4.2 + (math.sin(t * 6) if self.talking else math.sin(t * 1.6) * 0.5)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(93, 202, 165, 60))
            p.drawEllipse(QPoint(int(cx + 1), int(hy - r - 27)), int(pulse + 5), int(pulse + 5))
            p.setBrush(QColor(SPARK if self.talking else glow_c))
            p.drawEllipse(QPoint(int(cx + 1), int(hy - r - 27)), int(pulse), int(pulse))

    # ---- 尾巴 ----
    def _chibi_tail(self, p, cx, cy, t, spec):
        kind = spec["tail"]
        sway = math.sin(t * 1.9)
        if kind == "cat":
            path = QPainterPath()
            path.moveTo(cx + 16, cy + 34)
            path.quadTo(cx + 54, cy + 36 + sway * 4, cx + 42 + sway * 5, cy + 4)
            p.setPen(QPen(QColor(spec["hair_sh"]), 11, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor(spec["hair"]), 7, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
        elif kind == "fox":
            path = QPainterPath()
            path.moveTo(cx + 18, cy + 32)
            path.quadTo(cx + 62, cy + 32 + sway * 4, cx + 53 + sway * 4, cy - 6)
            p.setPen(QPen(QColor(spec["hair_sh"]), 18, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor(spec["hair"]), 13, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            p.setBrush(QColor("#FFFFFF"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(int(cx + 53 + sway * 4), int(cy - 6)), 5, 5)
        elif kind == "curl":
            path = QPainterPath()
            path.moveTo(cx + 16, cy + 33)
            path.quadTo(cx + 50, cy + 38, cx + 47, cy + 14)
            path.quadTo(cx + 44, cy - 4, cx + 28, cy + 1)
            p.setPen(QPen(QColor(spec["hair_sh"]), 11, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor("#FBE9CF"), 7, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
        elif kind == "ball":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(spec["hair"]))
            p.drawEllipse(QPoint(int(cx + 30), int(cy + 34)), 10, 10)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPoint(int(cx + 30), int(cy + 34)), 6, 6)
        elif kind == "tiger":
            path = QPainterPath()
            path.moveTo(cx + 16, cy + 34)
            path.quadTo(cx + 56, cy + 36 + sway * 5, cx + 44 + sway * 5, cy + 4)
            p.setPen(QPen(QColor(spec["hair_sh"]), 12, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor(spec["hair_sh"]), 12, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            # 虎纹
            p.setPen(QPen(QColor(spec["stripes"]), 2.4, Qt.SolidLine, Qt.RoundCap))
            for i, frac in enumerate((0.25, 0.5, 0.75)):
                pt = path.pointAtPercent(frac)
                p.drawLine(int(pt.x() - 4), int(pt.y() - 5), int(pt.x() + 4), int(pt.y() + 5))

    # ---- 立绘（图片素材）----
    def _draw_image(self, p, cx, cy, t, name, blinking):
        """画立绘。成功返回 True，没有素材返回 False（交给矢量兜底）。

        按 idle 帧的尺寸统一缩放，换帧时人物大小不跳；底部对齐到脚部基线，
        再叠加呼吸浮动；说话时整体微放大，做出「有反应」的感觉。
        """
        fr = self._frames(name)
        if not fr:
            return False
        ref = fr.get("idle") or next(iter(fr.values()))
        if blinking and "blink" in fr:
            pm = fr["blink"]
        elif self.talking and "talk" in fr:
            pm = fr["talk"]
        else:
            pm = ref
        bob = math.sin(t * 1.7) * 3.2
        grow = 1.03 if self.talking else 1.0
        # 注意：paintEvent 已经 p.scale(self._s) 过了，这里用未缩放坐标系
        avail_w, avail_h = 118.0 * grow, 134.0 * grow
        scale = min(avail_h / ref.height(), avail_w / ref.width())
        w, h = ref.width() * scale, ref.height() * scale
        x = cx - w / 2.0
        y = cy + 54 - h + bob              # 底部对齐到脚部基线
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(x, y, w, h), pm, QRectF(pm.rect()))
        return True

    def _draw_pet(self, p, cx, cy, t, blinking, glow_c):
        name = self._skin
        if name in self.IMAGE_SKINS:
            if self._draw_image(p, cx, cy, t, name, blinking):
                return
            name = self.IMAGE_SKINS[name][2]   # 缺图 → 退回矢量画法
        self._draw_chibi(p, cx, cy, t, blinking, name, glow_c)

    # ---- 主入口 ----
    def _draw_chibi(self, p, cx, cy, t, blinking, name, glow_c):
        spec = self.CHIBI.get(name) or self.CHIBI["cat"]
        jud = 5 if spec.get("jelly") else 0
        breath = math.sin(t * 1.7) * 1.5
        hy = cy - 15 + breath * 0.3
        r = 32 + jud
        sway = math.sin(t * 1.3)

        self._chibi_tail(p, cx, cy, t, spec)

        # 身体（Q 版：小身体大头）
        bw = 40 + jud
        body = QLinearGradient(0, cy + 6, 0, cy + 48)
        body.setColorAt(0.0, QColor(spec["hair"]))
        body.setColorAt(1.0, QColor(spec["hair_sh"]))
        p.setPen(QPen(QColor(spec["hair_sh"]), 1.2))
        p.setBrush(QBrush(body))
        p.drawRoundedRect(int(cx - bw / 2), int(cy + 8), int(bw), 38, 15, 15)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(spec["skin"]))
        for s in (-1, 1):   # 手
            p.drawEllipse(QPoint(int(cx + s * (bw / 2 - 3)), int(cy + 25)), 6, 6.5)
        p.setBrush(QColor(spec["hair_sh"]))
        for s in (-1, 1):   # 脚
            p.drawEllipse(QPoint(int(cx + s * 11), int(cy + 45)), 7, 5)

        self._chibi_ears(p, cx, hy, r, t, spec, sway)

        # 头
        head = QRadialGradient(cx - r * 0.35, hy - r * 0.45, r * 0.35)
        head.setColorAt(0.0, QColor(spec["skin"]).lighter(105))
        head.setColorAt(1.0, QColor(spec["skin"]))
        p.setPen(QPen(QColor(spec["hair_sh"]).lighter(125), 1.2))
        p.setBrush(QBrush(head))
        p.drawEllipse(QPoint(int(cx), int(hy)), r, int(r * 1.02))

        # 熊猫黑眼圈
        if spec.get("panda"):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#333333"))
            for s in (-1, 1):
                p.save()
                p.translate(cx + s * 13.5, hy + 7)
                p.rotate(s * 18)
                p.drawEllipse(QPoint(0, 0), 10, 12)
                p.restore()

        self._chibi_hair(p, cx, hy, r, t, spec, sway)

        # 虎纹（额头）
        if spec.get("stripes"):
            p.setPen(QPen(QColor(spec["stripes"]), 2.6, Qt.SolidLine, Qt.RoundCap))
            for dx in (-7, 0, 7):
                p.drawLine(int(cx + dx), int(hy - r * 0.66), int(cx + dx * 1.3), int(hy - r * 0.34))
            p.setPen(Qt.NoPen)

        self._chibi_eyes(p, cx, hy, spec, blinking, self.talking, t)

        # 腮红
        bc = QColor(spec["blush"])
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bc.red(), bc.green(), bc.blue(), 95))
        for s in (-1, 1):
            p.drawEllipse(QPoint(int(cx + s * 21), int(hy + 14)), 5.5, 3.4)

        self._chibi_mouth(p, cx, hy, spec, t)
        self._chibi_acc(p, cx, hy, r, t, spec, glow_c)


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
        # 候选位先按「气泡本体」算，再整体减掉留白换算成窗口位置。
        # 外移量里带上 m：窗口外框（含箭头所在的留白区）才不会压到桌宠身上。
        cands = (
            (g.right() - 20, g.top() - bodyH - 8 - m),         # 桌宠右上
            (g.left() - bodyW + 20, g.top() - bodyH - 8 - m),  # 桌宠左上
            (g.right() + m, g.top() + 8),                      # 桌宠右侧
            (g.left() - bodyW - m, g.top() + 8),               # 桌宠左侧
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
