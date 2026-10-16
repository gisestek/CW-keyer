"""Main window: one text stream for RX and TX, input line, macros, STOP."""
from __future__ import annotations

import copy
import datetime as dt
import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontDatabase, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..app import Station
from ..core.adif import band_for
from ..core.callsigns import find_callsigns
from ..core.i18n import tr
from .call_panel import CallPanel
from .colors import station_color
from .waterfall import WaterfallWidget

RX_COLOR = QColor("#1b1b1b")
TX_COLOR = QColor("#c0392b")
TIME_COLOR = QColor("#8a8a8a")
REF_COLOR = QColor("#7d8a96")
CALL_COLOR = QColor("#1f6fb2")
TX_PREFIX_W = 14          # "HH:MM:SSZ TX  "
TX_REF_LAG_S = 1.0        # decoded sidetone may be timed slightly before the first echo
NOTE_COLOR = QColor("#b9770e")
MAX_BLOCKS = 5000
TUNE_ARM_MS = 3000        # the second TUNE click must come within this time


class BusBridge(QObject):
    """Delivers bus messages to the GUI thread."""

    message = Signal(dict)

    def __init__(self, bus):
        super().__init__()
        bus.subscribe("*", self.message.emit)


class MainWindow(QMainWindow):
    def __init__(self, station: Station):
        super().__init__()
        self.station = station
        self.settings = station.settings
        self.bus = station.bus
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self._last_kind: str | None = None   # kind of the last line in the stream: RX, TX, NOTE
        self._rx_block = None
        self._rx_last_t = 0.0
        self._tx_blocks: list[dict] = []     # {start, last, tx: QTextBlock, ref: QTextBlock|None}
        self._cur_tx: dict | None = None
        self._queued = ""
        self._tx_busy = False
        self._rx_station = 0                 # station whose text the current RX line holds
        self._rx_wpm: float | None = None    # last measured speed of the other station
        self._stations: dict[int, tuple[float, float]] = {}   # index -> (pitch Hz, last heard)
        self._rx_rst: tuple[str, float] | None = None          # suggested report and its SNR

        self._build_ui()
        self._build_menu()
        self._restore_geometry()

        self.bridge = BusBridge(self.bus)
        self.bridge.message.connect(self._on_message)

        self._wpm_timer = QTimer(self, singleShot=True, interval=250)
        self._wpm_timer.timeout.connect(lambda: self.bus.publish("tx.set", wpm=self.wpm.value()))
        # TUNE button state: released when the keyer reports idle, on STOP, or at the latest by this timer
        self._tune_timer = QTimer(self, singleShot=True)
        self._tune_timer.timeout.connect(lambda: self._set_tune_state("idle"))
        self._tune_arm_timer = QTimer(self, singleShot=True, interval=TUNE_ARM_MS)
        self._tune_arm_timer.timeout.connect(lambda: self._tune_state == "armed" and self._set_tune_state("idle"))
        self._set_tune_state("idle")
        # a callsign picked up from the decoded text is looked up once it has stayed put for a moment
        self._lookup_timer = QTimer(self, singleShot=True, interval=1500)
        self._lookup_timer.timeout.connect(self._auto_lookup)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        self.sim_banner = QLabel(tr("keyer.simulated"))
        self.sim_banner.setAlignment(Qt.AlignCenter)
        self.sim_banner.setStyleSheet("background:#f4d03f;color:#000;font-weight:bold;padding:4px;")
        self.sim_banner.setVisible(self.station.sim_keyer)
        root.addWidget(self.sim_banner)
        self._build_update_bar(root)

        top = QHBoxLayout()
        self.keyer_label = QLabel(tr("keyer.disconnected"))
        self.keyer_label.setStyleSheet(self._chip("#922b21"))
        top.addWidget(self.keyer_label)
        self.tx_lamp = QLabel(tr("tx.idle"))
        self.tx_lamp.setAlignment(Qt.AlignCenter)
        self.tx_lamp.setMinimumWidth(56)
        self._set_tx_lamp(False)
        top.addWidget(self.tx_lamp)
        top.addStretch(1)
        top.addWidget(QLabel(tr("tx.wpm")))
        self.wpm = QSpinBox(minimum=5, maximum=50, value=int(self.settings.get("keyer.wpm", 20)))
        self.wpm.setMinimumWidth(70)
        self.wpm.valueChanged.connect(lambda _: self._wpm_timer.start())
        top.addWidget(self.wpm)
        self.match_btn = QPushButton(tr("rx.match"))
        self.match_btn.setToolTip(tr("rx.match.tip"))
        self.match_btn.setEnabled(False)
        self.match_btn.clicked.connect(self._match_speed)
        top.addWidget(self.match_btn)
        self.rx_info = QLabel("")
        self.rx_info.setMinimumWidth(230)
        self.rx_info.setToolTip(tr("rx.info.tip"))
        self.rx_info.setStyleSheet("color:#5a5a5a;")
        top.addWidget(self.rx_info)
        top.addSpacing(16)
        top.addWidget(QLabel(tr("wf.label")))
        self.wf_seconds = QComboBox()
        for sec in (6, 12, 18, 30):
            self.wf_seconds.addItem(f"{sec} s", sec)
        self.wf_seconds.setCurrentIndex(max(0, self.wf_seconds.findData(int(self.settings.get("ui.waterfall_seconds", 12)))))
        top.addWidget(self.wf_seconds)
        top.addSpacing(16)
        top.addWidget(QLabel(tr("qso.freq")))
        self.freq = QDoubleSpinBox(minimum=0.0, maximum=1300.0, decimals=4, singleStep=0.001,
                                   value=float(self.settings.get("qso.freq_mhz") or 0))
        self.freq.setSuffix(" MHz")
        self.freq.setMinimumWidth(110)
        self.freq.valueChanged.connect(self._freq_changed)
        top.addWidget(self.freq)
        self.band_label = QLabel(band_for(self.freq.value()) or "–")
        self.band_label.setMinimumWidth(38)
        top.addWidget(self.band_label)
        # TUNE next to the frequency: first click arms it, a second click within TUNE_ARM_MS keys the carrier
        self.tune_btn = QPushButton(tr("tx.tune"))
        self.tune_btn.setFocusPolicy(Qt.NoFocus)
        self.tune_btn.setMinimumWidth(78)
        self.tune_btn.setToolTip(tr("tx.tune.tip", s=self.settings.get("keyer.tune_s", 5)))
        self.tune_btn.clicked.connect(self._tune_clicked)
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.tune_btn.click, context=Qt.ApplicationShortcut)
        top.addWidget(self.tune_btn)
        root.addLayout(top)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(int(self.settings.get("ui.font_size", 13)))
        self.stream = QTextEdit(readOnly=True)
        self.stream.setFont(mono)
        self.stream.document().setMaximumBlockCount(MAX_BLOCKS)
        self.stream.setLineWrapMode(QTextEdit.WidgetWidth)
        self.stream.setMouseTracking(True)
        self.stream.mouseReleaseEvent = self._stream_clicked
        self.waterfall = WaterfallWidget(self.station.tx_windows, int(self.wf_seconds.currentData()))
        self.wf_seconds.currentIndexChanged.connect(self._wf_seconds_changed)
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.waterfall)
        # decoded text usually fills only the left part of the window: callsign details on the right
        self.call_panel = CallPanel(self.settings)
        self.call_panel.use_in_qso.connect(self._use_qrz_in_qso)
        self.call_panel.lookup_requested.connect(lambda c: self.station.qrz.lookup(c))
        self.call_split = QSplitter(Qt.Horizontal)
        self.call_split.setHandleWidth(4)
        self.call_split.addWidget(self.stream)
        self.call_split.addWidget(self.call_panel)
        self.call_split.setStretchFactor(0, 1)
        self.call_split.setStretchFactor(1, 0)
        self.call_split.setCollapsible(0, False)
        csizes = self.settings.get("ui.call_splitter")
        self.call_split.setSizes(csizes if isinstance(csizes, list) and len(csizes) == 2 else [700, 270])
        self.call_panel.setVisible(bool(self.settings.get("ui.call_panel", True)))
        self.splitter.addWidget(self.call_split)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        sizes = self.settings.get("ui.splitter")
        self.splitter.setSizes(sizes if isinstance(sizes, list) and len(sizes) == 2 else [170, 400])
        root.addWidget(self.splitter, 1)

        self.pending = QLabel("")
        self.pending.setFont(mono)
        self.pending.setStyleSheet("color:#7f8c8d;font-style:italic;")
        self.pending.setMinimumHeight(mono.pointSize() * 2)
        root.addWidget(self.pending)

        self.queue_label = QLabel("")
        self.queue_label.setFont(mono)
        self.queue_label.setStyleSheet("color:#c0392b;")
        root.addWidget(self.queue_label)

        qso_row = QHBoxLayout()
        self.qso_fields = {}
        for name, width in (("call", 110), ("name", 90), ("qth", 110), ("rst_sent", 50), ("rst_rcvd", 50)):
            qso_row.addWidget(QLabel(tr(f"qso.{name}")))
            edit = QLineEdit()
            edit.setMaximumWidth(width)
            edit.editingFinished.connect(lambda n=name: self.station.qso.set_field(n, self.qso_fields[n].text().strip()))
            qso_row.addWidget(edit)
            self.qso_fields[name] = edit
        self.qso_clear = QPushButton(tr("qso.clear"))
        self.qso_clear.clicked.connect(lambda: self.station.qso.clear())
        qso_row.addWidget(self.qso_clear)
        qso_row.addStretch(1)
        root.addLayout(qso_row)

        bottom = QHBoxLayout()
        left = QVBoxLayout()
        self.input = QLineEdit(placeholderText=tr("tx.input.placeholder"))
        big = QFont(mono)
        big.setPointSize(mono.pointSize() + 2)
        self.input.setFont(big)
        self.input.returnPressed.connect(self._send_input)
        left.addWidget(self.input)
        macro_row = QHBoxLayout()
        self.macro_buttons = {}
        for key in sorted((self.settings.get("macros") or {}).keys()):
            m = self.settings.get(f"macros.{key}") or {}
            btn = QPushButton(f"{key}  {m.get('label', '')}")
            btn.setToolTip(m.get("text", ""))
            btn.clicked.connect(lambda _=False, k=key: self._send_macro(k))
            QShortcut(QKeySequence(key), self, activated=lambda k=key: self._send_macro(k),
                      context=Qt.ApplicationShortcut)
            macro_row.addWidget(btn)
            self.macro_buttons[key] = btn
        self.cq_button = QPushButton(tr("cq.button"))
        self.cq_button.setCheckable(True)
        self.cq_button.clicked.connect(lambda _: self.station.cq.toggle())
        macro_row.addWidget(self.cq_button)
        self.log_button = QPushButton(tr("qso.log_button"))
        self.log_button.clicked.connect(self._log_qso)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._log_qso, context=Qt.ApplicationShortcut)
        macro_row.addWidget(self.log_button)
        macro_row.addStretch(1)
        left.addLayout(macro_row)
        bottom.addLayout(left, 1)

        self.stop_btn = QPushButton(tr("tx.stop"))
        self.stop_btn.setMinimumSize(120, 80)
        self.stop_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#c0392b;color:white;font-size:18px;font-weight:bold;border-radius:6px;}"
            "QPushButton:pressed{background:#922b21;}")
        self.stop_btn.setFocusPolicy(Qt.NoFocus)
        self.stop_btn.clicked.connect(lambda: self._stop("button"))
        bottom.addWidget(self.stop_btn)
        root.addLayout(bottom)

        # Esc works from any field (SR-01)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=lambda: self._stop("esc"),
                  context=Qt.ApplicationShortcut)

        self.setCentralWidget(central)

        sb = self.statusBar()
        self.level_bar = QProgressBar(minimum=-60, maximum=0, value=-60, textVisible=False)
        self.level_bar.setFixedWidth(160)
        self.level_bar.setFixedHeight(12)
        sb.addPermanentWidget(self.level_bar)
        self.level_label = QLabel("")
        sb.addPermanentWidget(self.level_label)
        self.level_warn = QLabel("")
        sb.addPermanentWidget(self.level_warn)
        sep = QFrame(frameShape=QFrame.VLine)
        sb.addPermanentWidget(sep)
        self.audio_label = QLabel(tr("rx.no_audio"))
        sb.addPermanentWidget(self.audio_label)

        self.input.setFocus()

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu(APP_NAME)
        act = QAction(tr("menu.settings"), self, triggered=self._open_settings, shortcut=QKeySequence("Ctrl+,"))
        m.addAction(act)
        m.addAction(QAction(tr("menu.open_log"), self, triggered=self._open_log))
        self.call_panel_action = QAction(tr("menu.call_panel"), self, checkable=True,
                                         checked=self.call_panel.isVisible(), shortcut=QKeySequence("Ctrl+K"))
        self.call_panel_action.toggled.connect(self._toggle_call_panel)
        m.addAction(self.call_panel_action)
        m.addSeparator()
        m.addAction(QAction(tr("menu.check_updates"), self,
                            triggered=lambda: self.station.updater.check(manual=True)))
        m.addAction(QAction(tr("menu.about"), self, triggered=self._about))
        m.addAction(QAction("Exit", self, triggered=self.close, shortcut=QKeySequence.Quit))

    @staticmethod
    def _chip(bg: str) -> str:
        return f"background:{bg};color:white;padding:3px 8px;border-radius:4px;font-weight:bold;"

    def _set_tx_lamp(self, on: bool) -> None:
        self.tx_lamp.setText(tr("tx.lamp") if on else tr("tx.idle"))
        self.tx_lamp.setStyleSheet(self._chip("#e74c3c" if on else "#7f8c8d"))

    # ------------------------------------------------------------------ actions
    def _send_input(self) -> None:
        text = self.input.text()
        if text.strip():
            self.bus.publish("tx.send", text=text)
            self.input.clear()

    def _send_macro(self, key: str) -> None:
        m = self.settings.get(f"macros.{key}") or {}
        if m.get("text"):
            self.bus.publish("tx.send", text=m["text"])

    def _set_tune_state(self, state: str) -> None:
        """idle -> armed ("Sure?") -> on (carrier). Only the keyer's answer (tx.tuning) turns it on."""
        self._tune_state = state
        if state == "armed":
            self.tune_btn.setText(tr("tx.tune.confirm"))
            self.tune_btn.setStyleSheet("QPushButton{background:#f4d03f;color:#000;font-weight:bold;}")
            self._tune_arm_timer.start()
        elif state == "on":
            self.tune_btn.setText(tr("tx.tune.on"))
            self.tune_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;font-weight:bold;}")
            self._tune_arm_timer.stop()
        else:
            self.tune_btn.setText(tr("tx.tune"))
            self.tune_btn.setStyleSheet("")
            self._tune_arm_timer.stop()
            self._tune_timer.stop()

    def _tune_clicked(self) -> None:
        """TUNE needs two clicks; while tuning, one click stops it (FR-TX-08)."""
        if self._tune_state == "on":
            self._stop("tune")
            self._set_tune_state("idle")
        elif self._tune_state == "idle":
            self._set_tune_state("armed")
        else:
            self._set_tune_state("idle")          # "on" only when the keyer accepted it (tx.tuning)
            if self.cq_button.isChecked():
                self.station.cq.stop("manual")
            self.bus.publish("tx.tune")

    def _stop(self, source: str) -> None:
        if getattr(self, "_tune_state", "idle") == "armed":
            self._set_tune_state("idle")
        self.bus.publish("tx.stop", reason=source)

    def _freq_changed(self, value: float) -> None:
        self.band_label.setText(band_for(value) or "–")
        self.settings.set("qso.freq_mhz", round(value, 4))
        if self.call_panel.call and self.call_panel.worked.isVisible():
            self._show_worked(self.call_panel.call)        # "new on this band" follows the band

    def _log_qso(self) -> None:
        from .qso_dialog import QsoDialog

        dlg = QsoDialog(self.station, self)
        if dlg.exec():
            try:
                dlg.commit()
            except OSError as e:
                QMessageBox.warning(self, tr("qso.title"), tr("qso.write_failed", msg=str(e)))
            self.freq.blockSignals(True)
            self.freq.setValue(float(self.settings.get("qso.freq_mhz") or 0))
            self.freq.blockSignals(False)

    def _stream_clicked(self, event) -> None:
        href = self.stream.anchorAt(event.pos())
        QTextEdit.mouseReleaseEvent(self.stream, event)
        if href.startswith("call:"):
            call = href[5:]
            self.station.qso.set_field("call", call)
            self.statusBar().showMessage(tr("qso.call_set", call=call), 4000)
            if not self.call_panel.isVisible():
                self.call_panel_action.setChecked(True)
            self.station.qrz.lookup(call)

    def _show_worked(self, call: str) -> None:
        if not call:
            return
        try:
            qsos = self.station.worked.lookup(call)
        except Exception:  # noqa: BLE001  a broken log file must not break the window
            return
        self.call_panel.show_worked(qsos, band_for(self.freq.value()))

    def _toggle_call_panel(self, on: bool) -> None:
        self.call_panel.setVisible(on)
        self.settings.set("ui.call_panel", bool(on))

    def _auto_lookup(self) -> None:
        call = self.station.qso.fields().get("call", "")
        if call and call != self.call_panel.call and self.call_panel.isVisible():
            self.station.qrz.lookup(call)

    def _use_qrz_in_qso(self, values: dict) -> None:
        """'Use in QSO': copy the QRZ name, QTH and locator into the QSO fields."""
        for name in ("call", "name", "qth", "gridsquare"):
            if values.get(name):
                self.station.qso.set_field(name, values[name])
        self.statusBar().showMessage(tr("qrz.used", call=values.get("call", "")), 4000)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog

        old = copy.deepcopy(self.settings.data)
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply()
            self.station.apply_settings(old)
            for key, btn in self.macro_buttons.items():
                m = self.settings.get(f"macros.{key}") or {}
                btn.setText(f"{key}  {m.get('label', '')}")
                btn.setToolTip(m.get("text", ""))
            self.tune_btn.setToolTip(tr("tx.tune.tip", s=self.settings.get("keyer.tune_s", 5)))
            if self.call_panel.call:
                self._show_worked(self.call_panel.call)
            self.wpm.blockSignals(True)
            self.wpm.setValue(int(self.settings.get("keyer.wpm", 20)))
            self.wpm.blockSignals(False)

    def _open_log(self) -> None:
        folder = self.settings.log_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------------ updates (FR-CORE-10)
    def _build_update_bar(self, root) -> None:
        self.update_bar = QFrame()
        self.update_bar.setObjectName("updateBar")
        self.update_bar.setStyleSheet("#updateBar{background:#e8f1fb;border:1px solid #b9d3ee;border-radius:4px;}"
                                      "#updateBar QLabel{background:transparent;}")
        lay = QHBoxLayout(self.update_bar)
        lay.setContentsMargins(10, 3, 6, 3)
        self.update_label = QLabel()
        lay.addWidget(self.update_label, 1)
        self.update_progress = QProgressBar(minimum=0, maximum=100, textVisible=True)
        self.update_progress.setFixedWidth(180)
        self.update_progress.setVisible(False)
        lay.addWidget(self.update_progress)
        self.update_notes_btn = QPushButton(tr("update.notes"))
        self.update_notes_btn.clicked.connect(self._update_notes)
        lay.addWidget(self.update_notes_btn)
        self.update_btn = QPushButton(tr("update.now"))
        self.update_btn.setStyleSheet("QPushButton{font-weight:bold;}")
        self.update_btn.clicked.connect(self._update_clicked)
        lay.addWidget(self.update_btn)
        self.update_skip_btn = QPushButton(tr("update.skip"))
        self.update_skip_btn.clicked.connect(self._update_skip)
        lay.addWidget(self.update_skip_btn)
        self.update_close_btn = QPushButton("✕")
        self.update_close_btn.setFlat(True)
        self.update_close_btn.setFixedWidth(28)
        self.update_close_btn.setToolTip(tr("update.later"))
        self.update_close_btn.clicked.connect(self._update_later)
        lay.addWidget(self.update_close_btn)
        for b in (self.update_notes_btn, self.update_btn, self.update_skip_btn, self.update_close_btn):
            b.setFocusPolicy(Qt.NoFocus)
        self.update_bar.setVisible(False)
        self._update: dict = {}
        self._update_state = "idle"          # idle | offered | downloading | ready
        root.addWidget(self.update_bar)

    def _on_update_message(self, t: str, m: dict) -> None:
        if t == "update.available":
            self._update = m
            self._update_state = "offered"
            size = f"{m.get('size', 0) / 1e6:.0f} MB" if m.get("size") else ""
            self.update_label.setText(tr("update.available", version=m.get("version", ""), size=size))
            self.update_btn.setText(tr("update.now") if m.get("one_click") else tr("update.download_page"))
            self.update_btn.setToolTip("" if m.get("one_click") else tr(f"update.why.{m.get('reason', 'source')}"))
            for b in (self.update_btn, self.update_notes_btn, self.update_skip_btn, self.update_close_btn):
                b.setVisible(True)
                b.setEnabled(True)
            self.update_progress.setVisible(False)
            self.update_bar.setVisible(True)
        elif t == "update.none" and m.get("manual"):
            QMessageBox.information(self, APP_NAME, tr("update.none", version=__version__))
        elif t == "update.error":
            if self._update_state == "downloading":
                self._update_state = "offered"
                self.update_progress.setVisible(False)
                self.update_btn.setEnabled(True)
                self.update_close_btn.setEnabled(True)
                self.update_btn.setText(tr("update.retry"))
                self.update_label.setText(tr("update.failed", msg=m.get("msg", "")))
            elif m.get("manual"):
                QMessageBox.warning(self, APP_NAME, tr("update.check_failed", msg=m.get("msg", "")))
        elif t == "update.progress":
            total = int(m.get("total") or 0)
            if total:
                self.update_progress.setValue(int(100 * int(m.get("done", 0)) / total))
        elif t == "update.ready":
            self._update_state = "ready"
            self.update_label.setText(tr("update.restarting", version=m.get("version", "")))
            self.update_progress.setVisible(False)
            if self._tx_busy or self._tune_state == "on":     # never restart in the middle of a transmission
                self._stop("update")
            QTimer.singleShot(300, self._install_update)

    def _update_clicked(self) -> None:
        m = self._update
        if not m:
            return
        if not m.get("one_click"):
            QDesktopServices.openUrl(QUrl(m.get("page", "")))
            return
        if self._tx_busy or self._tune_state == "on" or self.cq_button.isChecked():
            self.statusBar().showMessage(tr("update.wait_tx"), 6000)
            return
        call = self.station.qso.fields().get("call", "")
        if call and QMessageBox.question(self, APP_NAME, tr("update.qso_open", call=call)) != QMessageBox.Yes:
            return
        if not self.station.updater.start_download():
            return
        self._update_state = "downloading"
        self.update_label.setText(tr("update.downloading", version=m.get("version", "")))
        self.update_progress.setValue(0)
        self.update_progress.setVisible(True)
        self.update_btn.setEnabled(False)
        self.update_skip_btn.setVisible(False)
        self.update_notes_btn.setVisible(False)
        self.update_close_btn.setEnabled(False)

    def _install_update(self) -> None:
        from ..core.settings import config_dir

        try:
            self.station.updater.install_and_restart(config_dir() / "update.log")
        except Exception as e:  # noqa: BLE001
            self._on_update_message("update.error", {"msg": str(e)})
            self._update_state = "offered"
            return
        self.close()                      # STOP, settings saved; the helper swaps the folder and restarts

    def _update_notes(self) -> None:
        m = self._update
        box = QMessageBox(self)
        box.setWindowTitle(tr("update.notes_title", version=m.get("version", "")))
        box.setText(m.get("notes") or tr("update.no_notes"))
        box.setTextFormat(Qt.MarkdownText)
        open_btn = box.addButton(tr("update.open_page"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(m.get("page", "")))

    def _update_skip(self) -> None:
        self.settings.set("update.skip", self._update.get("version", ""))
        self._update_later()

    def _update_later(self) -> None:
        self.update_bar.setVisible(False)
        self._update_state = "idle"

    def _about(self) -> None:
        QMessageBox.about(self, APP_NAME, tr("about.text", version=__version__))

    # ------------------------------------------------------------------ stream
    def _wf_seconds_changed(self) -> None:
        sec = int(self.wf_seconds.currentData())
        self.waterfall.set_seconds(sec)
        self.settings.set("ui.waterfall_seconds", sec)

    @staticmethod
    def _stamp(t: float, label: str) -> str:
        return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%SZ") + f" {label:<2s}  "

    def _fmt(self, color: QColor, italic: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(color)
        f.setFontItalic(italic)
        return f

    def _near_bottom(self) -> bool:
        sb = self.stream.verticalScrollBar()
        return sb.value() >= sb.maximum() - 40

    def _scroll_if(self, was_bottom: bool) -> None:
        if was_bottom:
            sb = self.stream.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _insert_rx_text(self, cur: QTextCursor, text: str, color: QColor) -> None:
        """Insert decoded text, callsigns as clickable links (FR-CORE-03)."""
        pos = 0
        for start, end, call in find_callsigns(text):
            if start > pos:
                cur.insertText(text[pos:start], self._fmt(color))
            fmt = self._fmt(CALL_COLOR)
            fmt.setAnchor(True)
            fmt.setAnchorHref(f"call:{call}")
            fmt.setFontUnderline(True)
            cur.insertText(text[start:end], fmt)
            pos = end
        if pos < len(text):
            cur.insertText(text[pos:], self._fmt(color))

    def _new_line_at_end(self, prefix: str, text: str, color: QColor, italic: bool = False, rx: bool = False):
        doc = self.stream.document()
        cur = QTextCursor(doc)
        cur.movePosition(QTextCursor.End)
        if not doc.isEmpty():
            cur.insertBlock()
        if prefix:
            cur.insertText(prefix, self._fmt(TIME_COLOR))
        if rx:
            self._insert_rx_text(cur, text, color)
        else:
            cur.insertText(text, self._fmt(color, italic))
        return cur.block()

    def _append_to_block(self, block, text: str, color: QColor, rx: bool = False) -> bool:
        if block is None or not block.isValid():
            return False
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.EndOfBlock)
        if rx:
            self._insert_rx_text(cur, text, color)
        else:
            cur.insertText(text, self._fmt(color))
        return True

    def _insert_line_after(self, block, prefix: str, text: str, color: QColor):
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.EndOfBlock)
        cur.insertBlock()
        cur.insertText(prefix, self._fmt(TIME_COLOR))
        cur.insertText(text, self._fmt(color))
        return cur.block()

    def _is_last_block(self, block) -> bool:
        return block is not None and block.isValid() and block == self.stream.document().lastBlock()

    def _show_tx_char(self, ch: str) -> None:
        """Own transmission: one line per transmission, characters appended as the keyer sends them."""
        was = self._near_bottom()
        now = time.time()
        pause = float(self.settings.get("log.line_pause_s", 3.0))
        cur = self._cur_tx
        if cur and now - cur["last"] <= pause and self._append_to_block(cur["tx"], ch, TX_COLOR):
            cur["last"] = now
        else:
            block = self._new_line_at_end(self._stamp(now, "TX"), ch.lstrip(), TX_COLOR)
            self._cur_tx = {"start": now, "last": now, "tx": block, "ref": None}
            self._tx_blocks = [b for b in self._tx_blocks if b["tx"].isValid()][-30:] + [self._cur_tx]
            self._last_kind = "TX"
        self._scroll_if(was)

    def _show_rx(self, m: dict) -> None:
        was = self._near_bottom()
        text = m.get("text", "")
        t0 = m.get("t_start") or time.time()
        t1 = m.get("t_end") or t0
        if m.get("own_tx"):
            # decoded sidetone of our own transmission: reference line right under its TX line
            for blk in reversed(self._tx_blocks):
                if blk["start"] - TX_REF_LAG_S <= t1 and blk["tx"].isValid():
                    if blk["ref"] is not None and self._append_to_block(blk["ref"], " " + text, REF_COLOR):
                        pass
                    else:
                        blk["ref"] = self._insert_line_after(blk["tx"], " " * (TX_PREFIX_W - 5) + "ref  ",
                                                             text, REF_COLOR)
                    self._scroll_if(was)
                    return
        station = int(m.get("station") or 0)
        color = QColor(station_color(station))
        pause = float(self.settings.get("log.line_pause_s", 3.0))
        rx_open = self._rx_block is not None and self._rx_block.isValid() and station == self._rx_station and (
            (self._last_kind == "RX" and self._is_last_block(self._rx_block))
            # heard before our TX started but decoded after: keep it on the RX line above the TX line
            or (self._cur_tx is not None and t1 <= self._cur_tx["start"] + 0.5)
        )
        if rx_open and t0 - self._rx_last_t <= pause:
            self._append_to_block(self._rx_block, " " + text, color, rx=True)
        else:
            self._rx_block = self._new_line_at_end(self._stamp(t0, "RX"), text, color, rx=True)
            self._last_kind = "RX"
        self._rx_station = station
        self._rx_last_t = t1
        self._scroll_if(was)

    def _show_signal(self, m: dict) -> None:
        """Other station's speed and pitch (FR-RX-09): toolbar text and waterfall markers."""
        wpm, tone, delta = m.get("wpm"), m.get("tone_hz"), m.get("delta_hz")
        snr, rst = m.get("snr_db"), m.get("rst")
        if tone:
            self._stations[int(m.get("station", 0))] = (tone, time.time())
            self.waterfall.set_stations([(hz, idx, t) for idx, (hz, t) in self._stations.items()])
        if wpm:
            self._rx_wpm = wpm
            self.match_btn.setEnabled(abs(round(wpm) - self.wpm.value()) >= 1)
        parts = []
        if self._rx_wpm:
            parts.append(tr("rx.speed", wpm=round(self._rx_wpm)))
        if delta is not None and abs(delta) >= 10:
            parts.append(tr("rx.offset", delta=f"{delta:+.0f}"))
        if rst and snr is not None and int(m.get("station") or 0) == 0:
            self._rx_rst = (rst, snr)
        if getattr(self, "_rx_rst", None):
            parts.append(tr("rx.report", rst=self._rx_rst[0], snr=f"{self._rx_rst[1]:+.0f}"))
        self.rx_info.setText("  ".join(parts))

    def _match_speed(self) -> None:
        """Set our sending speed to the other station's speed."""
        if not self._rx_wpm:
            return
        wpm = max(self.wpm.minimum(), min(self.wpm.maximum(), int(round(self._rx_wpm))))
        self.wpm.setValue(wpm)          # valueChanged sends tx.set
        self.match_btn.setEnabled(False)
        self._note(tr("rx.matched", wpm=wpm))

    def _note(self, text: str) -> None:
        was = self._near_bottom()
        self._new_line_at_end("", text, NOTE_COLOR, italic=True)
        self._last_kind = "NOTE"
        self._scroll_if(True if was else False)

    def _update_queue_label(self) -> None:
        q = self._queued.strip()
        self.queue_label.setText(tr("tx.queue", text=q[:120]) if q else "")

    # ------------------------------------------------------------------ bus
    def _on_message(self, m: dict) -> None:
        t = m["type"]
        if t.startswith("update."):
            self._on_update_message(t, m)
            return
        if t == "rx.spectrum":
            self.waterfall.add_spectrum(m)
        elif t == "rx.text":
            self._show_rx(m)
        elif t == "rx.signal":
            self._show_signal(m)
        elif t == "rx.pending":
            self.pending.setText(m.get("text", "")[-160:])
        elif t == "rx.level":
            self.level_bar.setValue(int(max(-60, min(0, m["rms_dbfs"]))))
            self.waterfall.set_tone(m.get("tone_hz") if m.get("warning") != "weak" else None)
            self.level_label.setText(tr("rx.level", rms=m["rms_dbfs"], tone=m["tone_hz"]))
            w = m.get("warning", "")
            self.level_warn.setText(tr(f"rx.warn.{w}") if w else "")
            self.level_warn.setStyleSheet("color:#c0392b;font-weight:bold;" if w == "clip" else "color:#b9770e;")
        elif t == "rx.status":
            state = m.get("state")
            if state == "running":
                self.audio_label.setText(tr("rx.device", name=m.get("source", "")))
            elif state == "error":
                msg = m.get("msg", "")
                if msg.startswith("model_missing:"):
                    text = tr("rx.model_missing", path=msg.split(":", 1)[1])
                else:
                    text = tr("rx.error", msg=msg)
                self.audio_label.setText(tr("rx.no_audio"))
                self._note(text)
            else:
                self.audio_label.setText(tr("rx.no_audio"))
        elif t == "tx.echo":
            ch = m.get("ch", "")
            self._show_tx_char(ch)
            idx = self._queued.find(ch)
            if idx >= 0:
                self._queued = self._queued[idx + 1:]
            self._update_queue_label()
        elif t == "tx.queued":
            self._queued += m.get("text", "")
            self._update_queue_label()
        elif t == "tx.tuning":
            self._set_tune_state("on")
            self._tune_timer.start(int(m.get("ms", 5000)) + 1500)
            self._note(tr("tx.tuning", s=f"{m.get('ms', 0) / 1000:g}"))
        elif t == "tx.state":
            if not m.get("busy") and self._tune_state == "on":
                self._set_tune_state("idle")
            self._tx_busy = bool(m.get("busy"))
            self._set_tx_lamp(self._tx_busy)
            if not self._tx_busy:
                self._queued = ""
                self._update_queue_label()
        elif t == "tx.stopped":
            if self._tune_state == "on":
                self._set_tune_state("idle")
            had = bool(self._queued.strip()) or self._tx_busy
            self._queued = ""
            self._update_queue_label()
            self._set_tx_lamp(False)
            reason = m.get("reason", "")
            if had and reason not in ("shutdown",) and not reason.isupper():  # faults have their own note
                if reason in ("", "host", "button", "esc", "ota", "tune"):
                    self._note(tr("tx.stopped"))
                else:
                    self._note(tr("tx.stopped.reason", reason=tr(f"tx.stop_reason.{reason}")))
        elif t == "tx.fault":
            code = m.get("code", "")
            self._note(tr(f"tx.fault.{code}"))
        elif t == "tx.warning":
            code = m.get("code")
            text = {"not_connected": tr("tx.not_connected"),
                    "dropped_chars": tr("tx.dropped", chars=m.get("detail", "")),
                    "no_callsign": tr("tx.no_callsign"),
                    "no_call": tr("tx.no_call"),
                    "tune_busy": tr("tx.tune_busy")}.get(code, code)
            self.statusBar().showMessage(text, 8000)
            if code in ("not_connected", "no_callsign", "no_call"):
                self._note(text)
        elif t == "keyer.status":
            state = m.get("state")
            host = m.get("host", "")
            if state == "connected":
                self.keyer_label.setText(tr("keyer.connected", host=host))
                self.keyer_label.setStyleSheet(self._chip("#1e8449"))
                self.keyer_label.setToolTip(tr("keyer.fw", fw=m.get("fw", ""), version=m.get("version", "")))
            elif state == "connecting":
                self.keyer_label.setText(tr("keyer.connecting", host=host))
                self.keyer_label.setStyleSheet(self._chip("#b9770e"))
            else:
                self.keyer_label.setText(tr("keyer.disconnected"))
                self.keyer_label.setStyleSheet(self._chip("#922b21"))
                self._set_tx_lamp(False)
        elif t == "qso.update":
            f = m.get("fields", {})
            for name, edit in self.qso_fields.items():
                if not edit.hasFocus() and edit.text() != f.get(name, ""):
                    edit.setText(f.get(name, ""))
            if f.get("call") and f["call"] != self.call_panel.call and self.settings.get("qrz.auto", True):
                self._lookup_timer.start()
        elif t == "qrz.result":
            self.call_panel.show_result(m)
            if m.get("state") != "busy":
                self._show_worked(m.get("call", ""))
        elif t == "qso.logged":
            self._note(tr("qso.logged", call=m.get("call", ""), path=m.get("path", "")))
            if self.call_panel.call:
                self._show_worked(self.call_panel.call)
            for edit in self.qso_fields.values():
                edit.clear()
        elif t == "wavelog.status":
            state = m.get("state")
            if state == "sent":
                self.statusBar().showMessage(tr("wavelog.sent", call=m.get("call", "")), 6000)
            elif state == "duplicate":
                self.statusBar().showMessage(tr("wavelog.duplicate", call=m.get("call", "")), 6000)
            elif state == "rejected":
                self._note(tr("wavelog.rejected", call=m.get("call", ""), msg=m.get("msg", "")[:200]))
            elif state == "error":
                self.statusBar().showMessage(tr("wavelog.error", msg=m.get("msg", ""),
                                                pending=m.get("pending", 0)), 10000)
            elif state == "queued" and m.get("pending", 0) > 1:
                self.statusBar().showMessage(tr("wavelog.queued", pending=m.get("pending", 0)), 6000)
        elif t == "cq.state":
            self.cq_button.setChecked(bool(m.get("active")))
            if not m.get("active") and m.get("reason") == "answer":
                self._note(tr("cq.stopped_answer"))
        elif t == "keyer.error":
            self.statusBar().showMessage(f"Keyer: {m.get('code')} {m.get('msg', '')}", 8000)

    # ------------------------------------------------------------------ window
    def _restore_geometry(self) -> None:
        geo = self.settings.get("ui.window")
        if isinstance(geo, list) and len(geo) == 4:
            self.setGeometry(*geo)
        else:
            self.resize(980, 640)

    def closeEvent(self, event) -> None:  # noqa: N802
        g = self.geometry()
        self.settings.set("ui.window", [g.x(), g.y(), g.width(), g.height()])
        self.settings.set("ui.splitter", self.splitter.sizes())
        if self.call_panel.isVisible():
            self.settings.set("ui.call_splitter", self.call_split.sizes())
        self.station.shutdown()  # STOP before the window goes away (SR-05)
        event.accept()
