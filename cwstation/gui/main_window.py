"""Main window: one text stream for RX and TX, input line, macros, STOP."""
from __future__ import annotations

import copy
import datetime as dt
import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontDatabase, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..app import Station
from ..core.i18n import tr

RX_COLOR = QColor("#1b1b1b")
TX_COLOR = QColor("#c0392b")
TIME_COLOR = QColor("#8a8a8a")
NOTE_COLOR = QColor("#b9770e")
MAX_BLOCKS = 5000


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
        self._dir: str | None = None
        self._last_t = 0.0
        self._queued = ""
        self._tx_busy = False

        self._build_ui()
        self._build_menu()
        self._restore_geometry()

        self.bridge = BusBridge(self.bus)
        self.bridge.message.connect(self._on_message)

        self._wpm_timer = QTimer(self, singleShot=True, interval=250)
        self._wpm_timer.timeout.connect(lambda: self.bus.publish("tx.set", wpm=self.wpm.value()))

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
        root.addLayout(top)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(int(self.settings.get("ui.font_size", 13)))
        self.stream = QTextEdit(readOnly=True)
        self.stream.setFont(mono)
        self.stream.document().setMaximumBlockCount(MAX_BLOCKS)
        self.stream.setLineWrapMode(QTextEdit.WidgetWidth)
        root.addWidget(self.stream, 1)

        self.pending = QLabel("")
        self.pending.setFont(mono)
        self.pending.setStyleSheet("color:#7f8c8d;font-style:italic;")
        self.pending.setMinimumHeight(mono.pointSize() * 2)
        root.addWidget(self.pending)

        self.queue_label = QLabel("")
        self.queue_label.setFont(mono)
        self.queue_label.setStyleSheet("color:#c0392b;")
        root.addWidget(self.queue_label)

        bottom = QHBoxLayout()
        left = QVBoxLayout()
        self.input = QLineEdit(placeholderText=tr("tx.input.placeholder"))
        big = QFont(mono)
        big.setPointSize(mono.pointSize() + 2)
        self.input.setFont(big)
        self.input.returnPressed.connect(self._send_input)
        left.addWidget(self.input)
        macro_row = QHBoxLayout()
        self.macro_buttons = []
        for key in ("F1", "F2", "F3"):
            m = self.settings.get(f"macros.{key}") or {}
            btn = QPushButton(f"{key}  {m.get('label', '')}")
            btn.setToolTip(m.get("text", ""))
            btn.clicked.connect(lambda _=False, k=key: self._send_macro(k))
            QShortcut(QKeySequence(key), self, activated=lambda k=key: self._send_macro(k),
                      context=Qt.ApplicationShortcut)
            macro_row.addWidget(btn)
            self.macro_buttons.append(btn)
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
        m.addSeparator()
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

    def _stop(self, source: str) -> None:
        self.bus.publish("tx.stop", reason=source)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog

        old = copy.deepcopy(self.settings.data)
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply()
            self.station.apply_settings(old)
            for btn, key in zip(self.macro_buttons, ("F1", "F2", "F3")):
                m = self.settings.get(f"macros.{key}") or {}
                btn.setText(f"{key}  {m.get('label', '')}")
                btn.setToolTip(m.get("text", ""))
            self.wpm.blockSignals(True)
            self.wpm.setValue(int(self.settings.get("keyer.wpm", 20)))
            self.wpm.blockSignals(False)

    def _open_log(self) -> None:
        folder = self.settings.log_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _about(self) -> None:
        QMessageBox.about(self, APP_NAME, tr("about.text", version=__version__))

    # ------------------------------------------------------------------ stream
    def _append(self, direction: str, text: str, t: float, color: QColor) -> None:
        pause = float(self.settings.get("log.line_pause_s", 3.0))
        cur = self.stream.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        new_line = self._dir != direction or (t - self._last_t) > pause
        if new_line:
            if not self.stream.document().isEmpty():
                cur.insertBlock()
            fmt.setForeground(TIME_COLOR)
            stamp = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%SZ")
            cur.insertText(f"{stamp} {direction}  ", fmt)
            text = text.lstrip()
        elif direction == "RX":
            text = " " + text
        fmt.setForeground(color)
        cur.insertText(text, fmt)
        self._dir, self._last_t = direction, t
        sb = self.stream.verticalScrollBar()
        if sb.value() >= sb.maximum() - 40:
            self.stream.setTextCursor(cur)
            self.stream.ensureCursorVisible()

    def _note(self, text: str) -> None:
        cur = self.stream.textCursor()
        cur.movePosition(QTextCursor.End)
        if not self.stream.document().isEmpty():
            cur.insertBlock()
        fmt = QTextCharFormat()
        fmt.setForeground(NOTE_COLOR)
        fmt.setFontItalic(True)
        cur.insertText(text, fmt)
        self._dir = None
        self.stream.setTextCursor(cur)
        self.stream.ensureCursorVisible()

    def _update_queue_label(self) -> None:
        q = self._queued.strip()
        self.queue_label.setText(tr("tx.queue", text=q[:120]) if q else "")

    # ------------------------------------------------------------------ bus
    def _on_message(self, m: dict) -> None:
        t = m["type"]
        if t == "rx.text":
            self._append("RX", m["text"], m.get("t_start") or time.time(), RX_COLOR)
        elif t == "rx.pending":
            self.pending.setText(m.get("text", "")[-160:])
        elif t == "rx.level":
            self.level_bar.setValue(int(max(-60, min(0, m["rms_dbfs"]))))
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
            self._append("TX", ch, time.time(), TX_COLOR)
            idx = self._queued.find(ch)
            if idx >= 0:
                self._queued = self._queued[idx + 1:]
            self._update_queue_label()
        elif t == "tx.queued":
            self._queued += m.get("text", "")
            self._update_queue_label()
        elif t == "tx.state":
            self._tx_busy = bool(m.get("busy"))
            self._set_tx_lamp(self._tx_busy)
            if not self._tx_busy:
                self._queued = ""
                self._update_queue_label()
        elif t == "tx.stopped":
            had = bool(self._queued.strip()) or self._tx_busy
            self._queued = ""
            self._update_queue_label()
            self._set_tx_lamp(False)
            reason = m.get("reason", "")
            if had and reason not in ("shutdown",) and not reason.isupper():  # faults have their own note
                if reason in ("", "host", "button", "esc", "ota"):
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
                    "no_callsign": tr("tx.no_callsign")}.get(code, code)
            self.statusBar().showMessage(text, 8000)
            if code in ("not_connected", "no_callsign"):
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
        self.station.shutdown()  # STOP before the window goes away (SR-05)
        event.accept()
