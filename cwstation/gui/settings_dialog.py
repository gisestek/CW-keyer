"""Settings dialog (UC10, FR-CORE-01, FR-RX-01)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from PySide6.QtCore import Qt

from ..core import i18n
from ..core.i18n import tr
from ..rx.audio import list_input_devices


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(520)
        tabs = QTabWidget()

        # Station
        w = QWidget(); f = QFormLayout(w)
        self.callsign = QLineEdit(settings.get("station.callsign", ""))
        self.name = QLineEdit(settings.get("station.name", ""))
        self.qth = QLineEdit(settings.get("station.qth", ""))
        self.locator = QLineEdit(settings.get("station.locator", ""))
        f.addRow(tr("settings.callsign"), self.callsign)
        f.addRow(tr("settings.name"), self.name)
        f.addRow(tr("settings.qth"), self.qth)
        f.addRow(tr("settings.locator"), self.locator)
        self.language = QComboBox()
        langs = i18n.available_languages()
        self.language.addItems(langs)
        cur = settings.get("ui.language", "en")
        if cur in langs:
            self.language.setCurrentText(cur)
        f.addRow(tr("settings.language"), self.language)
        self.font_size = QSpinBox(minimum=8, maximum=32, value=int(settings.get("ui.font_size", 13)))
        f.addRow(tr("settings.font_size"), self.font_size)
        f.addRow(QLabel(tr("settings.restart_note")))
        tabs.addTab(w, tr("settings.tab.station"))

        # Audio
        w = QWidget(); f = QFormLayout(w)
        self.device = QComboBox()
        self.device.addItem(tr("settings.device.default"), "")
        for label in list_input_devices():
            self.device.addItem(label, label)
        stored = settings.get("audio.device", "")
        idx = self.device.findData(stored)
        if idx < 0 and stored:
            self.device.addItem(stored, stored)
            idx = self.device.count() - 1
        self.device.setCurrentIndex(max(0, idx))
        f.addRow(tr("settings.device"), self.device)
        self.channel = QComboBox()
        self.channel.addItem(tr("settings.channel.left"), 0)
        self.channel.addItem(tr("settings.channel.right"), 1)
        self.channel.setCurrentIndex(int(settings.get("audio.channel", 0)))
        f.addRow(tr("settings.channel"), self.channel)
        self.samplerate = QComboBox()
        for sr in (48000, 44100):
            self.samplerate.addItem(str(sr), sr)
        self.samplerate.setCurrentIndex(max(0, self.samplerate.findData(int(settings.get("audio.samplerate", 48000)))))
        f.addRow(tr("settings.samplerate"), self.samplerate)
        tabs.addTab(w, tr("settings.tab.audio"))

        # Keyer
        w = QWidget(); f = QFormLayout(w)
        self.keyer_type = QComboBox()
        self.keyer_type.addItem(tr("settings.keyer.type.wifi"), "wifi")
        self.keyer_type.addItem(tr("settings.keyer.type.winkeyer"), "winkeyer")
        idx = self.keyer_type.findData(settings.get("keyer.type", "wifi"))
        self.keyer_type.setCurrentIndex(max(0, idx))
        self.keyer_type.currentIndexChanged.connect(self._keyer_type_changed)
        f.addRow(tr("settings.keyer.type"), self.keyer_type)
        self.url = QLineEdit(settings.get("keyer.url", ""))
        self.url_label = QLabel(tr("settings.keyer.url"))
        f.addRow(self.url_label, self.url)
        self.serial_port = QComboBox()
        self.serial_port.setEditable(True)
        self.serial_port.setMinimumWidth(260)
        stored_port = settings.get("keyer.serial_port", "")
        from ..tx.winkeyer_client import list_ports

        for label in list_ports():
            self.serial_port.addItem(label)
        self.serial_port.setEditText(stored_port)
        self.port_label = QLabel(tr("settings.keyer.port"))
        f.addRow(self.port_label, self.serial_port)
        self.wk_note = QLabel(tr("settings.keyer.winkeyer_note"))
        self.wk_note.setWordWrap(True)
        self.wk_note.setStyleSheet("color:#b9770e;")
        f.addRow(self.wk_note)
        self.wpm = QSpinBox(minimum=5, maximum=50, value=int(settings.get("keyer.wpm", 20)))
        f.addRow(tr("settings.keyer.wpm"), self.wpm)
        self.weight = QSpinBox(minimum=25, maximum=75, value=int(settings.get("keyer.weight", 50)))
        f.addRow(tr("settings.keyer.weight"), self.weight)
        self.keydown = QSpinBox(minimum=1000, maximum=10500, singleStep=500,
                                value=int(settings.get("keyer.keydown_max_ms", 10500)))
        f.addRow(tr("settings.keyer.keydown"), self.keydown)
        self.txmax = QSpinBox(minimum=10000, maximum=120000, singleStep=10000,
                              value=int(settings.get("keyer.tx_max_ms", 120000)))
        f.addRow(tr("settings.keyer.tx"), self.txmax)
        self.limits_note = QLabel(tr("settings.keyer.limits_note"))
        self.limits_note.setWordWrap(True)
        f.addRow(self.limits_note)
        tabs.addTab(w, tr("settings.tab.keyer"))
        self._keyer_type_changed()

        # Log
        w = QWidget(); f = QFormLayout(w)
        row = QHBoxLayout()
        self.log_folder = QLineEdit(str(settings.log_folder()))
        browse = QPushButton(tr("settings.log.browse"))
        browse.clicked.connect(self._browse)
        row.addWidget(self.log_folder, 1)
        row.addWidget(browse)
        f.addRow(tr("settings.log.folder"), row)
        self.pause = QDoubleSpinBox(minimum=1.0, maximum=60.0, singleStep=0.5,
                                    value=float(settings.get("log.line_pause_s", 3.0)))
        f.addRow(tr("settings.log.pause"), self.pause)
        tabs.addTab(w, tr("settings.tab.log"))

        # QSO / ADIF
        w = QWidget(); f = QFormLayout(w)
        row = QHBoxLayout()
        self.adif_file = QLineEdit(settings.get("qso.adif_file", ""))
        adif_browse = QPushButton(tr("settings.log.browse"))
        adif_browse.clicked.connect(self._browse_adif)
        row.addWidget(self.adif_file, 1)
        row.addWidget(adif_browse)
        f.addRow(tr("settings.qso.adif"), row)
        self.tx_pwr = QLineEdit(str(settings.get("qso.tx_pwr", "")))
        f.addRow(tr("settings.qso.power"), self.tx_pwr)
        self.cq_interval = QSpinBox(minimum=2, maximum=120, value=int(settings.get("cq.interval_s", 8)))
        f.addRow(tr("settings.cq.interval"), self.cq_interval)
        tabs.addTab(w, tr("qso.title"))

        # Wavelog
        w = QWidget(); f = QFormLayout(w)
        wl = settings.get("wavelog", {}) or {}
        self.wl_enabled = QCheckBox()
        self.wl_enabled.setChecked(bool(wl.get("enabled")))
        f.addRow(tr("settings.wavelog.enabled"), self.wl_enabled)
        self.wl_url = QLineEdit(wl.get("url", ""))
        self.wl_url.setPlaceholderText("https://wavelog.example.com")
        f.addRow(tr("settings.wavelog.url"), self.wl_url)
        self.wl_key = QLineEdit(wl.get("key", ""))
        self.wl_key.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        f.addRow(tr("settings.wavelog.key"), self.wl_key)
        self.wl_profile = QLineEdit(str(wl.get("station_profile_id", "")))
        f.addRow(tr("settings.wavelog.profile"), self.wl_profile)
        test = QPushButton(tr("settings.wavelog.test"))
        test.clicked.connect(self._test_wavelog)
        self.wl_result = QLabel("")
        self.wl_result.setWordWrap(True)
        f.addRow(test, self.wl_result)
        tabs.addTab(w, tr("settings.tab.wavelog"))

        # Macros
        w = QWidget(); lay = QVBoxLayout(w)
        keys = sorted((settings.get("macros") or {}).keys())
        self.macro_table = QTableWidget(len(keys), 3)
        self.macro_table.setHorizontalHeaderLabels(
            [tr("settings.macros.key"), tr("settings.macros.label"), tr("settings.macros.text")])
        self.macro_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.macro_table.verticalHeader().setVisible(False)
        for r, key in enumerate(keys):
            m = settings.get(f"macros.{key}") or {}
            item = QTableWidgetItem(key)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.macro_table.setItem(r, 0, item)
            self.macro_table.setItem(r, 1, QTableWidgetItem(m.get("label", "")))
            self.macro_table.setItem(r, 2, QTableWidgetItem(m.get("text", "")))
        lay.addWidget(self.macro_table)
        lay.addWidget(QLabel(tr("settings.macros.note")))
        tabs.addTab(w, tr("settings.tab.macros"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def _keyer_type_changed(self) -> None:
        winkey = self.keyer_type.currentData() == "winkeyer"
        for wdg in (self.url, self.url_label):
            wdg.setVisible(not winkey)
        for wdg in (self.serial_port, self.port_label, self.wk_note):
            wdg.setVisible(winkey)
        for wdg in (self.keydown, self.txmax, self.limits_note):
            wdg.setEnabled(not winkey)      # the safety limits live in our own keyer only

    def _browse_adif(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("settings.qso.adif"), self.adif_file.text() or "cwstation.adi",
                                              "ADIF (*.adi *.adif)")
        if path:
            self.adif_file.setText(path)

    def _test_wavelog(self) -> None:
        from ..core.bus import Bus
        from ..core.wavelog import WavelogClient

        probe = {"wavelog": {"enabled": True, "url": self.wl_url.text().strip(),
                             "key": self.wl_key.text().strip(),
                             "station_profile_id": self.wl_profile.text().strip()}}

        class _S:
            def get(self, name, default=None):
                return probe.get(name, default) if "." not in name else default

        client = WavelogClient(Bus(), _S(), self.s.path.parent / "wavelog-test.jsonl")
        ok, msg = client.post("<CALL:4>TEST<QSO_DATE:8>19700101<TIME_ON:6>000000<BAND:3>40m"
                              "<MODE:2>CW<RST_SENT:3>599<RST_RCVD:3>599<EOR>")
        self.wl_result.setText(tr("settings.wavelog.ok") if ok else tr("settings.wavelog.fail", msg=msg[:200]))

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("settings.log.folder"), self.log_folder.text())
        if d:
            self.log_folder.setText(d)

    def apply(self) -> None:
        s = self.s
        s.set("station.callsign", self.callsign.text().strip().upper())
        s.set("station.name", self.name.text().strip())
        s.set("station.qth", self.qth.text().strip())
        s.set("station.locator", self.locator.text().strip().upper())
        s.set("ui.language", self.language.currentText() or "en")
        s.set("ui.font_size", self.font_size.value())
        s.set("audio.device", self.device.currentData() or "")
        s.set("audio.channel", int(self.channel.currentData()))
        s.set("audio.samplerate", int(self.samplerate.currentData()))
        s.set("keyer.type", self.keyer_type.currentData() or "wifi")
        s.set("keyer.url", self.url.text().strip())
        s.set("keyer.serial_port", self.serial_port.currentText().strip())
        s.set("keyer.wpm", self.wpm.value())
        s.set("keyer.weight", self.weight.value())
        s.set("keyer.keydown_max_ms", self.keydown.value())
        s.set("keyer.tx_max_ms", self.txmax.value())
        s.set("log.folder", self.log_folder.text().strip())
        s.set("log.line_pause_s", self.pause.value())
        s.set("qso.adif_file", self.adif_file.text().strip())
        s.set("qso.tx_pwr", self.tx_pwr.text().strip())
        s.set("cq.interval_s", self.cq_interval.value())
        s.set("wavelog.enabled", self.wl_enabled.isChecked())
        s.set("wavelog.url", self.wl_url.text().strip())
        s.set("wavelog.key", self.wl_key.text().strip())
        s.set("wavelog.station_profile_id", self.wl_profile.text().strip())
        for r in range(self.macro_table.rowCount()):
            key = self.macro_table.item(r, 0).text()
            s.set(f"macros.{key}.label", (self.macro_table.item(r, 1) or QTableWidgetItem("")).text().strip())
            s.set(f"macros.{key}.text", (self.macro_table.item(r, 2) or QTableWidgetItem("")).text().strip())
