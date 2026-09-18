"""QSO summary window: check the fields suggested by the decoder and log the contact (UC6)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from ..core.adif import band_for
from ..core.i18n import tr


class QsoDialog(QDialog):
    def __init__(self, station, parent=None):
        super().__init__(parent)
        self.station = station
        self.s = station.settings
        f = station.qso.fields()
        self.setWindowTitle(tr("qso.title"))
        self.setMinimumWidth(420)
        form = QFormLayout()

        self.call = QLineEdit(f.get("call", ""))
        self.rst_sent = QLineEdit(f.get("rst_sent", "") or "599")
        self.rst_rcvd = QLineEdit(f.get("rst_rcvd", "") or "599")
        self.name = QLineEdit(f.get("name", ""))
        self.qth = QLineEdit(f.get("qth", ""))
        self.grid = QLineEdit(f.get("gridsquare", ""))
        self.comment = QLineEdit(f.get("comment", ""))
        self.freq = QDoubleSpinBox(minimum=0.0, maximum=1300.0, decimals=4, singleStep=0.001,
                                   value=float(self.s.get("qso.freq_mhz") or 0))
        self.freq.setSuffix(" MHz")
        self.band = QLabel(band_for(self.freq.value()) or "–")
        self.freq.valueChanged.connect(lambda v: self.band.setText(band_for(v) or "–"))
        self.power = QLineEdit(str(self.s.get("qso.tx_pwr", "")))
        self.wavelog = QCheckBox(tr("qso.to_wavelog"))
        self.wavelog.setChecked(station.wavelog.enabled())
        self.wavelog.setEnabled(station.wavelog.enabled())

        form.addRow(tr("qso.call"), self.call)
        form.addRow(tr("qso.rst_sent"), self.rst_sent)
        form.addRow(tr("qso.rst_rcvd"), self.rst_rcvd)
        form.addRow(tr("qso.name"), self.name)
        form.addRow(tr("qso.qth"), self.qth)
        form.addRow(tr("qso.grid"), self.grid)
        form.addRow(tr("qso.freq"), self.freq)
        form.addRow(tr("qso.band"), self.band)
        form.addRow(tr("qso.power"), self.power)
        form.addRow(tr("qso.comment"), self.comment)
        form.addRow("", self.wavelog)
        form.addRow(QLabel(tr("qso.file", path=str(station.adif_path()))))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("qso.log"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)
        self.call.setFocus()

    def commit(self) -> dict:
        """Store the edited values and write the QSO."""
        q = self.station.qso
        q.set_field("call", self.call.text().strip().upper())
        q.set_field("rst_sent", self.rst_sent.text().strip())
        q.set_field("rst_rcvd", self.rst_rcvd.text().strip())
        q.set_field("name", self.name.text().strip())
        q.set_field("qth", self.qth.text().strip())
        q.set_field("gridsquare", self.grid.text().strip().upper())
        q.set_field("comment", self.comment.text().strip())
        self.s.set("qso.freq_mhz", round(self.freq.value(), 4))
        self.s.set("qso.tx_pwr", self.power.text().strip())
        self.s.save()
        return self.station.log_qso(freq_mhz=self.freq.value() or None,
                                    tx_pwr=self.power.text().strip(),
                                    to_wavelog=self.wavelog.isChecked())
