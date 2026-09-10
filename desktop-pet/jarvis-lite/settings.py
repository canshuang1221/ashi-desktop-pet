import os
import time

import requests
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSlider, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget, QLabel,
)

import config
import pet as pet_mod
import theme


class ModelFetcher(QThread):
    """拉取 /v1/models，填充下拉。"""

    got = Signal(list, str)

    def __init__(self, base_url, key):
        super().__init__()
        self.base_url, self.key = base_url, key

    def run(self):
        try:
            r = requests.get(
                self.base_url.rstrip("/") + "/models",
                headers={"Authorization": "Bearer " + self.key},
                timeout=15,
            )
        except Exception as e:
            self.got.emit([], str(e)[:150])
            return
        if r.status_code == 200:
            try:
                ids = sorted(m.get("id", "") for m in r.json().get("data", []))
                self.got.emit([i for i in ids if i], "")
            except Exception as e:
                self.got.emit([], "解析失败: " + str(e)[:100])
        else:
            self.got.emit([], "%s %s" % (r.status_code, r.text[:100]))


class ConnTester(QThread):
    """发一个最小请求验证连通性，顺带测延迟。"""

    done = Signal(bool, str)

    def __init__(self, base_url, key, model):
        super().__init__()
        self.base_url, self.key, self.model = base_url, key, model

    def run(self):
        t = time.time()
        try:
            r = requests.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + self.key,
                         "Content-Type": "application/json"},
                json={"model": self.model,
                      "messages": [{"role": "user", "content": "hi"}],
                      "max_tokens": 5},
                timeout=25,
            )
        except Exception as e:
            self.done.emit(False, str(e)[:120])
            return
        dt = time.time() - t
        if r.status_code == 200:
            self.done.emit(True, "%.1f 秒" % dt)
        else:
            self.done.emit(False, "%s %s" % (r.status_code, r.text[:80]))


class Settings(QDialog):
    """分页签设置：API / 基本设置 / UI。

    UI 页的滑条实时预览：桌宠缩放直接改 pet，字号/气泡宽度写进 cfg
    （气泡每次 say 都重新读 cfg，对话面板在保存时应用）。
    取消或关窗时还原全部实时改动。
    """

    def __init__(self, cfg, on_save, pet=None, chat=None):
        super().__init__()
        self.cfg = cfg
        self.on_save = on_save
        self.pet = pet
        self.chat = chat
        self._fetcher = None
        self._tester = None
        self._orig_scale = float(cfg["pet"].get("scale", 1.0))
        self._orig_skin = cfg["pet"].get("skin", "cat")
        self._orig_ui = dict(cfg.get("ui", {}))
        self.setWindowTitle("设置")
        self.setFixedWidth(560)
        self.setStyleSheet(theme.app_qss())
        self._build()

    # ---------- 页签 ----------
    def _build(self):
        tabs = QTabWidget()
        tabs.addTab(self._tab_api(), "API")
        tabs.addTab(self._tab_basic(), "基本设置")
        tabs.addTab(self._tab_ui(), "外观")
        tabs.addTab(self._tab_data(), "数据")

        row = QHBoxLayout()
        save = QPushButton("保存")
        cancel = QPushButton("取消")
        save.setObjectName("primary")
        save.setMinimumWidth(92)
        cancel.setObjectName("ghost")
        cancel.setMinimumWidth(92)
        save.setFixedHeight(34)
        cancel.setFixedHeight(34)
        save.setCursor(Qt.PointingHandCursor)
        cancel.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)
        root.addWidget(tabs)
        root.addLayout(row)

    def _tab_api(self):
        a = self.cfg["api"]
        w = QW_()
        f = QFormLayout(w)
        f.setSpacing(10)

        self.base_url = QLineEdit(a["base_url"])
        self.api_key = QLineEdit(a["api_key"])
        self.api_key.setEchoMode(QLineEdit.Password)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setCurrentText(a["model"])
        self.btn_models = QPushButton("获取列表")
        self.btn_models.setFixedHeight(26)
        self.btn_models.setCursor(Qt.PointingHandCursor)
        self.btn_models.clicked.connect(self.fetch_models)
        self.mrow = QHBoxLayout()
        self.mrow.setSpacing(6)
        self.mrow.addWidget(self.model, 1)
        self.mrow.addWidget(self.btn_models)

        self.vision = QComboBox()
        self.vision.setEditable(True)
        self.vision.addItem("")
        self.vision.setCurrentText(a["vision_model"])
        self.vision.setPlaceholderText("留空 = 用上面的模型")

        self.temp = QSpinBox()
        self.temp.setRange(0, 20)
        self.temp.setValue(int(a["temperature"] * 10))

        self.btn_test = QPushButton("测试连接")
        self.btn_test.setFixedHeight(28)
        self.btn_test.setCursor(Qt.PointingHandCursor)
        self.btn_test.clicked.connect(self.test_conn)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#888780;font-size:12px;")
        ops = QHBoxLayout()
        ops.addWidget(self.btn_test)
        ops.addWidget(self.status, 1)

        f.addRow("API 地址", self.base_url)
        f.addRow("API Key", self.api_key)
        f.addRow("模型", self.mrow)
        f.addRow("视觉模型", self.vision)
        f.addRow("温度(×10)", self.temp)
        f.addRow("", ops)
        return w

    def _tab_basic(self):
        w = QW_()
        f = QFormLayout(w)
        f.setSpacing(10)

        self.persona = QPlainTextEdit(self.cfg["persona"])
        self.persona.setFixedHeight(90)

        self.interval = QSpinBox()
        self.interval.setRange(20, 3600)
        self.interval.setValue(self.cfg["sense"]["interval_sec"])
        self.interval.setSuffix(" 秒")
        self.sense = QCheckBox("开启屏幕感知（定期看屏幕并搭话）")
        self.sense.setChecked(self.cfg["sense"]["enabled"])

        self.tick_interval = QSpinBox()
        self.tick_interval.setRange(120, 7200)
        self.tick_interval.setValue(self.cfg["tick"]["interval_sec"])
        self.tick_interval.setSuffix(" 秒")
        self.tick = QCheckBox("定时主动搭话（不看屏幕，几乎零延迟、几乎不花钱）")
        self.tick.setChecked(self.cfg["tick"]["enabled"])

        self.idle_thr = QSpinBox()
        self.idle_thr.setRange(60, 3600)
        self.idle_thr.setValue(self.cfg["idle"]["threshold_sec"])
        self.idle_thr.setSuffix(" 秒")
        self.idle = QCheckBox("键鼠空闲时自动休息（不再自言自语）")
        self.idle.setChecked(self.cfg["idle"]["enabled"])

        # 截图范围：活跃窗口画面密度高、看得清；整屏能看到全局但小字会变糊
        self.shot_scope = QComboBox()
        self.shot_scope.addItem("只截当前活跃窗口（推荐，看得清）", "window")
        self.shot_scope.addItem("整个屏幕", "screen")
        _i = self.shot_scope.findData(self.cfg["sense"].get("shot_scope", "window"))
        self.shot_scope.setCurrentIndex(max(0, _i))

        # 截图清晰度：调大能看清代码小字，但截图体积（以及 token）会变大
        self.shot_scale = QSpinBox()
        self.shot_scale.setRange(40, 100)
        self.shot_scale.setSuffix(" %")
        self.shot_scale.setValue(
            int(float(self.cfg["sense"].get("shot_scale", 0.85)) * 100))
        self.shot_quality = QSpinBox()
        self.shot_quality.setRange(40, 95)
        self.shot_quality.setValue(int(self.cfg["sense"].get("shot_quality", 82)))

        # 保留最近几张截图：只留一张的话，回头看「它当时看到了啥」就没依据了
        self.keep_shots = QSpinBox()
        self.keep_shots.setRange(0, 30)
        self.keep_shots.setSuffix(" 张")
        self.keep_shots.setValue(int(self.cfg["sense"].get("keep_shots", 8)))

        f.addRow("人设", self.persona)
        f.addRow("看屏间隔", self.interval)
        f.addRow("", self.sense)
        f.addRow("截图范围", self.shot_scope)
        f.addRow("截图清晰度", self.shot_scale)
        f.addRow("截图画质", self.shot_quality)
        f.addRow("保留截图", self.keep_shots)
        f.addRow("搭话间隔", self.tick_interval)
        f.addRow("", self.tick)
        f.addRow("空闲阈值", self.idle_thr)
        f.addRow("", self.idle)
        return w

    def _tab_ui(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setSpacing(10)

        self.pet_name = QLineEdit()
        self.pet_name.setMaxLength(12)
        self.pet_name.setText(self.cfg["pet"].get("name", "阿拾"))
        self.pet_name.setPlaceholderText("给它起个名字")

        self.scale = QSlider(Qt.Horizontal)
        self.scale.setRange(50, 220)
        self.scale.setValue(int(self.cfg["pet"].get("scale", 1.0) * 100))
        self.scale.setTickPosition(QSlider.TicksBelow)
        self.scale.setTickInterval(10)
        self.scale_lbl = QLabel()
        self.srow = QHBoxLayout()
        self.srow.setSpacing(8)
        self.srow.addWidget(self.scale, 1)
        self.srow.addWidget(self.scale_lbl)
        self.scale.valueChanged.connect(self._scale_live)
        self._scale_live(self.scale.value())

        self.skin = QComboBox()
        # 形象列表直接取自 pet.Pet.SKINS，加新形象只需改 pet.py 一处
        for val in pet_mod.Pet.available():
            self.skin.addItem(pet_mod.Pet.label(val), val)
        cur = self.cfg["pet"].get("skin", "cat")
        idx = self.skin.findData(cur)
        self.skin.setCurrentIndex(idx if idx >= 0 else 0)
        # 换形象立即生效，不用等保存
        self.skin.currentIndexChanged.connect(self._skin_live)

        self.font_sz = QSlider(Qt.Horizontal)
        self.font_sz.setRange(9, 18)
        self.font_sz.setValue(int(self.cfg.get("ui", {}).get("font_size", 12)))
        self.font_lbl = QLabel()
        self.frow = QHBoxLayout()
        self.frow.setSpacing(8)
        self.frow.addWidget(self.font_sz, 1)
        self.frow.addWidget(self.font_lbl)
        self.font_sz.valueChanged.connect(self._font_live)
        self._font_live(self.font_sz.value())

        self.bub_w = QSlider(Qt.Horizontal)
        self.bub_w.setRange(180, 420)
        self.bub_w.setValue(int(self.cfg.get("ui", {}).get("bubble_width", 260)))
        self.bub_lbl = QLabel()
        self.brow = QHBoxLayout()
        self.brow.setSpacing(8)
        self.brow.addWidget(self.bub_w, 1)
        self.brow.addWidget(self.bub_lbl)
        self.bub_w.valueChanged.connect(self._bw_live)
        self._bw_live(self.bub_w.value())

        self.bub_ms = QSlider(Qt.Horizontal)
        self.bub_ms.setRange(3, 60)
        self.bub_ms.setValue(max(3, min(60, int(self.cfg.get("ui", {}).get("bubble_ms", 7000)) // 1000)))
        self.ms_lbl = QLabel()
        self.msrow = QHBoxLayout()
        self.msrow.setSpacing(8)
        self.msrow.addWidget(self.bub_ms, 1)
        self.msrow.addWidget(self.ms_lbl)
        self.bub_ms.valueChanged.connect(self._ms_live)
        self._ms_live(self.bub_ms.value())

        f.addRow("名字", self.pet_name)
        f.addRow("形象", self.skin)
        f.addRow("桌宠缩放", self.srow)
        f.addRow("字号", self.frow)
        f.addRow("气泡宽度", self.brow)
        f.addRow("气泡留存", self.msrow)
        tip = QLabel("缩放拖动即时生效，取消则还原。字号、气泡宽度与留存时间保存后生效；"
                     "换成别的形象保存后立刻生效。")
        tip.setStyleSheet("color:%s;font-size:12px;" % theme.TEXT_SUB)
        tip.setWordWrap(True)
        f.addRow("", tip)
        return w

    # ---------- 数据 ----------
    def _tab_data(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setSpacing(10)

        tip = QLabel(
            "三样东西别再搞混了：\n"
            "· 对话记录：按天的聊天流水账，只保留最近 60 条，用来当聊天上下文。\n"
            "· 长期记忆：它从聊天里提炼出「关于你这个人」的事实，越用越懂你。\n"
            "· 今日足迹：它从屏幕里看到的你一天在干什么（看视频/工作/摸鱼/打游戏…），"
            "不需要你开口说话也能积累。\n"
            "清空都会先弹确认，不放托盘里就是为了防误触。")
        tip.setStyleSheet("color:%s;font-size:12px;" % theme.TEXT_SUB)
        tip.setWordWrap(True)

        self.btn_clear_chat = QPushButton("清空对话记录")
        self.btn_clear_chat.setObjectName("ghost")
        self.btn_clear_chat.setCursor(Qt.PointingHandCursor)
        self.btn_clear_chat.clicked.connect(self._do_clear_chat)

        self.btn_clear_memo = QPushButton("清空它对我的长期记忆")
        self.btn_clear_memo.setObjectName("ghost")
        self.btn_clear_memo.setCursor(Qt.PointingHandCursor)
        self.btn_clear_memo.clicked.connect(self._do_clear_memo)

        self.btn_open_memo = QPushButton("打开长期记忆文件（看得见、可手改）")
        self.btn_open_memo.setObjectName("ghost")
        self.btn_open_memo.setCursor(Qt.PointingHandCursor)
        self.btn_open_memo.clicked.connect(self._open_memo)

        self.btn_open_dir = QPushButton("打开数据文件夹")
        self.btn_open_dir.setObjectName("ghost")
        self.btn_open_dir.setCursor(Qt.PointingHandCursor)
        self.btn_open_dir.clicked.connect(lambda: os.startfile(config.BASE_DIR))

        self.btn_activity = QPushButton("今天都干了什么（今日足迹）")
        self.btn_activity.setObjectName("ghost")
        self.btn_activity.setCursor(Qt.PointingHandCursor)
        self.btn_activity.clicked.connect(self._open_activity)

        self.btn_shots = QPushButton("最近的截图（它看到了啥）")
        self.btn_shots.setObjectName("ghost")
        self.btn_shots.setCursor(Qt.PointingHandCursor)
        self.btn_shots.clicked.connect(
            lambda: self._open_dir(os.path.join(config.BASE_DIR, "shots")))

        f.addRow("", tip)
        f.addRow("", self.btn_clear_chat)
        f.addRow("", self.btn_clear_memo)
        f.addRow("", self.btn_open_memo)
        f.addRow("", self.btn_activity)
        f.addRow("", self.btn_shots)
        f.addRow("", self.btn_open_dir)
        return w

    def _open_dir(self, d):
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            QMessageBox.warning(self, "打不开", str(e)[:120])

    def _brain(self):
        """取到 brain（挂在对话面板上）；拿不到就返回 None。"""
        return getattr(self.chat, "brain", None)

    def _do_clear_chat(self):
        if QMessageBox.question(
                self, "确认清空对话记录",
                "清空全部对话流水账？（长期记忆不受影响）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        brain = self._brain()
        if brain is not None:
            brain.clear_history()
        if self.chat is not None:
            self.chat.clear()
        QMessageBox.information(self, "完成", "对话记录已清空。")

    def _do_clear_memo(self):
        if QMessageBox.question(
                self, "确认清空长期记忆",
                "清空它提炼的、关于你的长期记忆？\n（对话记录不受影响）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        brain = self._brain()
        if brain is not None:
            brain.clear_user_memo()
        QMessageBox.information(self, "完成", "长期记忆已清空。")

    def _open_activity(self):
        """弹窗看今日足迹：耗时排行 + 要点总结。

        以前是直接打开 activity/ 文件夹，用户只看到一堆 json，等于没看到内容。
        """
        from history import Activity
        self._act_win = Activity(self.cfg)
        self._act_win.show()
        self._act_win.raise_()
        self._act_win.activateWindow()

    def _open_memo(self):
        """弹窗看长期记忆。

        原先用 os.startfile 打开 .md，系统没关联程序时会静默失败，
        跟「点了没反应」一样，所以改成自己弹窗。
        """
        from history import Memo
        self._memo_win = Memo(self.cfg)
        self._memo_win.show()
        self._memo_win.raise_()
        self._memo_win.activateWindow()

    # ---------- 滑条实时预览 ----------
    def _scale_live(self, v):
        self.scale_lbl.setText("%d%%" % v)
        if self.pet is not None:
            self.pet.apply_scale(v / 100.0)

    def _skin_live(self, _idx=None):
        """换形象立即应用（和缩放滑条一样实时预览，取消则还原）。"""
        if self.pet is None:
            return
        self.pet.set_skin(self.skin.currentData() or "cat")

    def _font_live(self, v):
        self.font_lbl.setText("%d px" % v)
        self.cfg.setdefault("ui", {})["font_size"] = v

    def _bw_live(self, v):
        self.bub_lbl.setText("%d px" % v)
        self.cfg.setdefault("ui", {})["bubble_width"] = v

    def _ms_live(self, v):
        self.ms_lbl.setText("%d 秒" % v)
        self.cfg.setdefault("ui", {})["bubble_ms"] = v * 1000

    def reject(self):
        # 取消/关窗：还原所有实时改动
        if self.pet is not None:
            self.pet.apply_scale(self._orig_scale)
            self.pet.set_skin(self._orig_skin)
        self.cfg["ui"] = dict(self._orig_ui)
        super().reject()

    # ---------- 模型列表 ----------
    def fetch_models(self):
        if not self.api_key.text().strip():
            self.status.setText("先填 API Key")
            return
        self.status.setText("获取中…")
        self.btn_models.setEnabled(False)
        self._fetcher = ModelFetcher(self.base_url.text().strip(), self.api_key.text().strip())
        self._fetcher.got.connect(self._fill_models)
        self._fetcher.start()

    def _fill_models(self, ids, err):
        self.btn_models.setEnabled(True)
        if err:
            self.status.setText("获取失败: " + err[:80])
            self.status.setStyleSheet("color:#A32D2D;font-size:12px;")
            return
        cur, curv = self.model.currentText(), self.vision.currentText()
        self.model.clear()
        self.model.addItems(ids)
        self.vision.clear()
        self.vision.addItem("")
        self.vision.addItems(ids)
        self.model.setCurrentText(cur)
        self.vision.setCurrentText(curv)
        self.status.setText("已获取 %d 个模型" % len(ids))
        self.status.setStyleSheet("color:#0F6E56;font-size:12px;")

    # ---------- 连接测试 ----------
    def test_conn(self):
        model = self.model.currentText().strip()
        if not self.api_key.text().strip() or not model:
            self.status.setText("需要 API Key 和模型名")
            return
        self.status.setText("测试中…")
        self.btn_test.setEnabled(False)
        self._tester = ConnTester(
            self.base_url.text().strip(), self.api_key.text().strip(), model
        )
        self._tester.done.connect(self._test_done)
        self._tester.start()

    def _test_done(self, ok, msg):
        self.btn_test.setEnabled(True)
        if ok:
            self.status.setText("连接成功 (" + msg + ")")
            self.status.setStyleSheet("color:#0F6E56;font-size:12px;")
        else:
            self.status.setText("失败: " + msg[:80])
            self.status.setStyleSheet("color:#A32D2D;font-size:12px;")

    def _save(self):
        a = self.cfg["api"]
        a["base_url"] = self.base_url.text().strip()
        a["api_key"] = self.api_key.text().strip()
        a["model"] = self.model.currentText().strip()
        a["vision_model"] = self.vision.currentText().strip()
        a["temperature"] = self.temp.value() / 10.0
        self.cfg["pet"]["scale"] = self.scale.value() / 100.0
        self.cfg["pet"]["skin"] = self.skin.currentData() or "cat"
        self.cfg["ui"]["font_size"] = self.font_sz.value()
        self.cfg["ui"]["bubble_width"] = self.bub_w.value()
        self.cfg["ui"]["bubble_ms"] = self.bub_ms.value() * 1000
        self.cfg["persona"] = self.persona.toPlainText().strip()
        self.cfg["sense"]["enabled"] = self.sense.isChecked()
        self.cfg["sense"]["interval_sec"] = self.interval.value()
        self.cfg["sense"]["shot_scope"] = self.shot_scope.currentData() or "window"
        self.cfg["pet"]["name"] = (self.pet_name.text().strip() or "阿拾")
        self.cfg["sense"]["shot_scale"] = self.shot_scale.value() / 100.0
        self.cfg["sense"]["shot_quality"] = self.shot_quality.value()
        self.cfg["sense"]["keep_shots"] = self.keep_shots.value()
        self.cfg["tick"]["enabled"] = self.tick.isChecked()
        self.cfg["tick"]["interval_sec"] = self.tick_interval.value()
        self.cfg["idle"]["enabled"] = self.idle.isChecked()
        self.cfg["idle"]["threshold_sec"] = self.idle_thr.value()
        self.on_save(self.cfg)
        self.accept()


def QW_():
    from PySide6.QtWidgets import QWidget
    return QWidget()
