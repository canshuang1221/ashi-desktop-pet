"""桌面宠物的统一视觉主题。

所有窗口（设置 / 历史 / 对话）都从这里取色，改一处就整体一致。
对外主要提供 app_qss()：一段全局样式表，设置面板与历史窗口直接 setStyleSheet 用。
"""


import os
import config

# ---- 主色 ----
BRAND = "#185FA5"        # 主蓝（原版就有，保留作品牌色）
BRAND_DARK = "#0C447C"   # 主蓝按下态
BRAND_SOFT = "#E8F0FA"   # 主蓝浅底（悬停 / 选中）
MINT = "#5DCAA5"         # 强调绿
AMBER = "#EF9F27"        # 强调橙
DANGER = "#A32D2D"

# ---- 中性色 ----
BG = "#FFFFFF"           # 窗口底
CARD = "#F7F9FC"         # 卡片 / 输入框底
CARD_ALT = "#F2F3F5"     # 聊天区底（微信灰）
BORDER = "#E3E6EB"       # 常规描边
BORDER_SOFT = "#D3D1C7"  # 输入框描边
TEXT = "#2B2B2B"         # 正文
TEXT_SUB = "#8A9099"     # 次要说明
TEXT_WEAK = "#B0B6BF"    # 更弱的提示

RADIUS = 10              # 统一圆角



def _asset_path(name):
    """在素材目录列表里找第一个存在该文件的目录，返回正斜杠路径。

    打包成 exe 后 BASE_DIR/assets（exe 旁）可能不存在，
    需要回退到 sys._MEIPASS 里的打包素材，两个都试。
    """
    for d in config.ASSETS_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p.replace("\\", "/")
    return os.path.join(config.ASSETS_DIRS[0], name).replace("\\", "/")


def app_qss():
    """设置 / 历史等窗口的全局样式表。"""
    _arrow = _asset_path("dropdown_arrow.png")
    _arrow_hov = _asset_path("dropdown_arrow_hover.png")
    return """
    QDialog { background: %(BG)s; }
    QWidget { font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; color: %(TEXT)s; }
    QLabel { color: %(TEXT)s; background: transparent; }
    QLabel#hint { color: %(TEXT_SUB)s; font-size: 12px; }
    QLabel#title { color: %(BRAND)s; font-size: 15px; font-weight: 600; }

    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: %(CARD)s; border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS)s;
        padding: 6px 8px; color: %(TEXT)s; selection-background-color: %(BRAND)s;
        selection-color: #FFFFFF;
    }
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
        border: 1px solid %(BRAND)s; background: %(BG)s;
    }
    QLineEdit:disabled, QComboBox:disabled { color: %(TEXT_WEAK)s; }
    QComboBox::drop-down {
        border: none; width: 20px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }
    QComboBox::down-arrow {
        image: url("%(ARROW)s");
        width: 12px; height: 12px;
        margin-right: 2px;
    }
    QComboBox::down-arrow:on {
        image: url("%(ARROW_HOV)s");
    }
    QComboBox::down-arrow:hover {
        image: url("%(ARROW_HOV)s");
    }
    QComboBox QAbstractItemView {
        background: %(BG)s; border: 1px solid %(BORDER)s; border-radius: 6px;
        selection-background-color: %(BRAND_SOFT)s; selection-color: %(TEXT)s;
        outline: none; padding: 4px;
    }

    QPushButton {
        background: %(CARD)s; color: %(TEXT)s; border: 1px solid %(BORDER)s;
        border-radius: %(RADIUS)s; padding: 6px 14px;
    }
    QPushButton:hover { background: %(BRAND_SOFT)s; border-color: %(BRAND)s; color: %(BRAND)s; }
    QPushButton:pressed { background: %(BRAND_SOFT)s; }
    QPushButton#primary { background: %(BRAND)s; color: #FFFFFF; border: none; font-weight: 600; }
    QPushButton#primary:hover { background: %(BRAND_DARK)s; color: #FFFFFF; }
    QPushButton#ghost { background: transparent; border: 1px solid %(BORDER)s; color: %(TEXT_SUB)s; }

    QTabWidget::pane {
        border: 1px solid %(BORDER)s; border-radius: %(RADIUS)s;
        background: %(BG)s; top: -1px;
    }
    QTabBar::tab {
        background: transparent; color: %(TEXT_SUB)s; padding: 8px 16px;
        border-bottom: 2px solid transparent; margin-right: 4px;
    }
    QTabBar::tab:hover { color: %(BRAND)s; }
    QTabBar::tab:selected { color: %(BRAND)s; border-bottom: 2px solid %(BRAND)s; font-weight: 600; }

    QCheckBox { background: transparent; spacing: 7px; }
    QCheckBox::indicator {
        width: 15px; height: 15px; border: 1px solid %(BORDER_SOFT)s;
        border-radius: 4px; background: %(CARD)s;
    }
    QCheckBox::indicator:hover { border-color: %(BRAND)s; }
    QCheckBox::indicator:checked { background: %(BRAND)s; border-color: %(BRAND)s; }

    QSlider::groove:horizontal { height: 4px; background: %(BORDER)s; border-radius: 2px; }
    QSlider::sub-page:horizontal { background: %(BRAND)s; border-radius: 2px; }
    QSlider::handle:horizontal {
        background: #FFFFFF; border: 2px solid %(BRAND)s;
        width: 12px; height: 12px; margin: -6px 0; border-radius: 8px;
    }
    QSlider::handle:horizontal:hover { background: %(BRAND_SOFT)s; }

    QGroupBox {
        border: 1px solid %(BORDER)s; border-radius: %(RADIUS)s; background: %(CARD)s;
        margin-top: 16px; padding: 14px 10px 10px 10px;
    }
    QGroupBox::title {
        subcontrol-origin: margin; left: 12px; padding: 0 5px;
        color: %(BRAND)s; font-weight: 600; background: %(BG)s;
    }

    QScrollArea { border: none; background: transparent; }
    QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0; }
    QScrollBar::handle:vertical { background: #D6DAE0; border-radius: 4px; min-height: 26px; }
    QScrollBar::handle:vertical:hover { background: #BFC5CE; }
    QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
    QScrollBar:horizontal { background: transparent; height: 8px; }
    QScrollBar::handle:horizontal { background: #D6DAE0; border-radius: 4px; min-width: 26px; }

    QToolTip {
        background: #2E3440; color: #FFFFFF; border: none;
        border-radius: 6px; padding: 5px 8px;
    }
    """ % dict(globals(), ARROW=_arrow, ARROW_HOV=_arrow_hov)


def chat_qss(font_pt=12):
    """对话面板专用（气泡区 + 输入框）。"""
    return """
    QWidget#root { background: %(BG)s; border: 1px solid %(BORDER_SOFT)s; border-radius: 12px; }
    QLabel { color: %(BRAND)s; background: transparent; }
    QTextBrowser {
        background: %(CARD_ALT)s; border: 1px solid %(BORDER)s;
        border-radius: 8px; padding: 8px; font-size: %(pt)dpx;
    }
    QPlainTextEdit {
        background: %(CARD)s; border: 1px solid %(BORDER_SOFT)s;
        border-radius: 8px; padding: 6px; font-size: %(pt)dpx;
    }
    QPlainTextEdit:focus { border: 1px solid %(BRAND)s; background: %(BG)s; }
    """ % dict(globals(), pt=font_pt)
