"""Settings dialog (UC10, FR-CORE-01, FR-RX-01)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

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
        self.url = QLineEdit(settings.get("keyer.url", ""))
        f.addRow(tr("settings.keyer.url"), self.url)
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
        f.addRow(QLabel(tr("settings.keyer.limits_note")))
        tabs.addTab(w, tr("settings.tab.keyer"))

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

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

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
        s.set("keyer.url", self.url.text().strip())
        s.set("keyer.wpm", self.wpm.value())
        s.set("keyer.weight", self.weight.value())
        s.set("keyer.keydown_max_ms", self.keydown.value())
        s.set("keyer.tx_max_ms", self.txmax.value())
        s.set("log.folder", self.log_folder.text().strip())
        s.set("log.line_pause_s", self.pause.value())
