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
        self.splitter.addWidget(self.stream)
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

    def _freq_changed(self, value: float) -> None:
        self.band_label.setText(band_for(value) or "–")
        self.settings.set("qso.freq_mhz", round(value, 4))

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
            self.station.qso.set_field("call", href[5:])
            self.statusBar().showMessage(tr("qso.call_set", call=href[5:]), 4000)

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
        pause = float(self.settings.get("log.line_pause_s", 3.0))
        rx_open = self._rx_block is not None and self._rx_block.isValid() and (
            (self._last_kind == "RX" and self._is_last_block(self._rx_block))
            # heard before our TX started but decoded after: keep it on the RX line above the TX line
            or (self._cur_tx is not None and t1 <= self._cur_tx["start"] + 0.5)
        )
        if rx_open and t0 - self._rx_last_t <= pause:
            self._append_to_block(self._rx_block, " " + text, RX_COLOR, rx=True)
        else:
            self._rx_block = self._new_line_at_end(self._stamp(t0, "RX"), text, RX_COLOR, rx=True)
            self._last_kind = "RX"
        self._rx_last_t = t1
        self._scroll_if(was)

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
        if t == "rx.spectrum":
            self.waterfall.add_spectrum(m)
        elif t == "rx.text":
            self._show_rx(m)
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
                    "no_callsign": tr("tx.no_callsign"),
                    "no_call": tr("tx.no_call")}.get(code, code)
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
        elif t == "qso.logged":
            self._note(tr("qso.logged", call=m.get("call", ""), path=m.get("path", "")))
            for edit in self.qso_fields.values():
                edit.clear()
        elif t == "wavelog.status":
            state = m.get("state")
            if state == "sent":
                self.statusBar().showMessage(tr("wavelog.sent", call=m.get("call", "")), 6000)
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
        self.station.shutdown()  # STOP before the window goes away (SR-05)
        event.accept()
