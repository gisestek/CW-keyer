"""Callsign panel to the right of the text stream: QRZ.com details of a clicked callsign (FR-CORE-08)."""
from __future__ import annotations

import base64
import html

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QFormLayout, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ..core.geo import distance_bearing, grid_to_latlon
from ..core.i18n import tr
from ..core.qrz import web_url

PHOTO_MAX_W = 260
PHOTO_MAX_H = 200
HISTORY = 15
WORKED_ROWS = 5
NEW_COLOR = "#1e8449"
BAND_NEW_COLOR = "#b9770e"


def _name(d: dict) -> str:
    if d.get("name_fmt"):
        return d["name_fmt"]
    n = " ".join(p for p in (d.get("fname", ""), d.get("name", "")) if p).strip()
    return n.title() if n.isupper() else n


def qso_name(d: dict) -> str:
    """First name for the QSO / {NAME} macro: nickname, else the first given name."""
    n = d.get("nickname") or (d.get("fname") or "").split(" ")[0]
    return n.title() if n.isupper() or n.islower() else n


def qso_qth(d: dict) -> str:
    q = d.get("addr2", "")
    return q.title() if q.isupper() else q


class CallPanel(QFrame):
    """Shows one callsign. The window feeds it ``qrz.result`` messages."""

    use_in_qso = Signal(dict)       # {"name": …, "qth": …, "gridsquare": …}
    lookup_requested = Signal(str)  # a callsign from the history list

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.call = ""
        self._data: dict = {}
        self.setObjectName("callPanel")
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("#callPanel{background:#ffffff;border-left:1px solid #dcdcdc;}"
                           "#callPanel QLabel{background:transparent;}")
        self.setMinimumWidth(200)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(6)

        self.title = QLabel(tr("qrz.empty"))
        f = QFont(self.font())
        f.setPointSize(f.pointSize() + 7)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet("color:#1f6fb2;")
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.title)

        self.status = QLabel(tr("qrz.hint"))
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#7f8c8d;font-style:italic;")
        lay.addWidget(self.status)

        self.photo = QLabel()
        self.photo.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.photo.setVisible(False)
        lay.addWidget(self.photo)

        self.form_box = QWidget()
        self.form = QFormLayout(self.form_box)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(3)
        self.rows: dict[str, QLabel] = {}
        for key in ("name", "qth", "country", "grid", "dist", "class", "qsl", "zones"):
            val = QLabel()
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lbl = QLabel(tr(f"qrz.f.{key}"))
            lbl.setStyleSheet("color:#7f8c8d;")
            self.form.addRow(lbl, val)
            self.rows[key] = val
        lay.addWidget(self.form_box)

        self.worked = QLabel()
        self.worked.setWordWrap(True)
        self.worked.setTextFormat(Qt.RichText)
        self.worked.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.worked.setStyleSheet("padding-top:4px;")
        self.worked.setVisible(False)
        lay.addWidget(self.worked)

        btns = QHBoxLayout()
        self.use_btn = QPushButton(tr("qrz.use"))
        self.use_btn.setToolTip(tr("qrz.use.tip"))
        self.use_btn.clicked.connect(self._use)
        btns.addWidget(self.use_btn)
        self.web_btn = QPushButton(tr("qrz.web"))
        self.web_btn.setToolTip(tr("qrz.web.tip"))
        self.web_btn.clicked.connect(self._open_web)
        btns.addWidget(self.web_btn)
        btns.addStretch(1)
        lay.addLayout(btns)

        lay.addStretch(1)
        self.hist_label = QLabel(tr("qrz.history"))
        self.hist_label.setStyleSheet("color:#7f8c8d;")
        lay.addWidget(self.hist_label)
        self.history = QListWidget()
        self.history.setMaximumHeight(140)
        self.history.setStyleSheet("QListWidget{border:none;background:transparent;}")
        self.history.itemClicked.connect(lambda it: self.lookup_requested.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.history)

        self._show_rows({})
        self.use_btn.setEnabled(False)
        self.web_btn.setEnabled(False)
        self.hist_label.setVisible(False)
        self.history.setVisible(False)

    # -- updates --
    def show_result(self, m: dict) -> None:
        call = m.get("call", "")
        if not call:
            return
        state = m.get("state")
        if call != self.call:
            self.worked.setVisible(False)
            self.photo.clear()
            self.photo.setVisible(False)
            self._data = {}
            self._show_rows({})
        self.call = call
        self.title.setText(call)
        self.web_btn.setEnabled(True)
        if state == "busy":
            self.status.setText(tr("qrz.busy"))
            self.status.setVisible(True)
        elif state == "no_login":
            self.status.setText(tr("qrz.no_login"))
            self.status.setVisible(True)
        elif state == "not_found":
            self.status.setText(tr("qrz.not_found"))
            self.status.setVisible(True)
        elif state == "error":
            self.status.setText(tr("qrz.error", msg=m.get("msg", "")))
            self.status.setVisible(True)
        elif state == "ok":
            self._data = dict(m.get("data") or {})
            self._show_rows(self._data)
            self._show_photo(m.get("image_b64", ""))
            if m.get("subscriber") is False:
                self.status.setText(tr("qrz.limited"))
                self.status.setVisible(True)
            else:
                self.status.setVisible(False)
            self._add_history(call, _name(self._data))
        self.use_btn.setEnabled(bool(self._data))

    def show_worked(self, qsos: list[dict], band: str = "") -> None:
        """Earlier QSOs with the station shown (FR-CORE-09), newest first."""
        esc = html.escape
        band = (band or "").lower()
        if not qsos:
            text = f'<b style="color:{NEW_COLOR}">{esc(tr("worked.new"))}</b>'
        else:
            lines = [f'<b>{esc(tr("worked.count", n=len(qsos)))}</b>']
            bands = []
            for q in qsos:
                if q["band"] and q["band"] not in bands:
                    bands.append(q["band"])
            if bands:
                chips = " ".join(f"<b>{esc(b)}</b>" if b == band else esc(b) for b in bands)
                lines.append(f'{esc(tr("worked.bands"))} {chips}')
            if band and band not in bands:
                lines.append(f'<b style="color:{BAND_NEW_COLOR}">{esc(tr("worked.new_band", band=band))}</b>')
            rows = []
            for q in qsos[:WORKED_ROWS]:
                d = q["date"]
                date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
                rst = "/".join(r for r in (q["rst_sent"], q["rst_rcvd"]) if r)
                who = q["call"] if q["call"] != self.call else q["name"]   # e.g. worked as /P
                cells = [date, q["band"], rst, who]
                rows.append("<tr>" + "".join(f'<td style="padding-right:6px">{esc(c)}</td>' for c in cells)
                            + "</tr>")
            if len(qsos) > WORKED_ROWS:
                rows.append(f'<tr><td colspan="4" style="color:#7f8c8d">'
                            f'{esc(tr("worked.more", n=len(qsos) - WORKED_ROWS))}</td></tr>')
            lines.append('<table style="color:#5a5a5a">' + "".join(rows) + "</table>")
            text = "<br>".join(lines[:-1]) + lines[-1]
        self.worked.setText(text)
        self.worked.setVisible(True)

    def _show_rows(self, d: dict) -> None:
        qth = ", ".join(p for p in (qso_qth(d), d.get("state", "")) if p)
        qsl = []
        if d.get("lotw") == "1":
            qsl.append("LoTW")
        if d.get("eqsl") == "1":
            qsl.append("eQSL")
        if d.get("mqsl") == "1":
            qsl.append(tr("qrz.paper"))
        if d.get("qslmgr"):
            qsl.append(d["qslmgr"])
        zones = " / ".join(f"{k} {d[v]}" for k, v in (("CQ", "cqzone"), ("ITU", "ituzone")) if d.get(v))
        values = {
            "name": _name(d),
            "qth": qth,
            "country": d.get("country", ""),
            "grid": d.get("grid", "").upper(),
            "dist": self._distance(d),
            "class": d.get("class", ""),
            "qsl": ", ".join(qsl),
            "zones": zones,
        }
        for key, val in values.items():
            self.rows[key].setText(val)
            self.rows[key].setVisible(bool(val))
            self.form.labelForField(self.rows[key]).setVisible(bool(val))
        self.form_box.setVisible(any(values.values()))

    def _distance(self, d: dict) -> str:
        mine = grid_to_latlon(self.settings.get("station.locator", "") or "")
        if not mine:
            return ""
        theirs = None
        try:
            if d.get("lat") and d.get("lon"):
                theirs = (float(d["lat"]), float(d["lon"]))
        except ValueError:
            theirs = None
        theirs = theirs or grid_to_latlon(d.get("grid", ""))
        if not theirs:
            return ""
        km, deg = distance_bearing(mine, theirs)
        return tr("qrz.dist", km=f"{km:,.0f}".replace(",", " "), deg=f"{deg:.0f}")

    def _show_photo(self, b64: str) -> None:
        pm = QPixmap()
        if b64:
            try:
                pm.loadFromData(base64.b64decode(b64))
            except ValueError:
                pm = QPixmap()
        if pm.isNull():
            self.photo.setVisible(False)
            return
        w = min(PHOTO_MAX_W, max(120, self.width() - 30))
        self.photo.setPixmap(pm.scaled(w, PHOTO_MAX_H, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.photo.setVisible(True)

    def _add_history(self, call: str, name: str) -> None:
        for i in range(self.history.count()):
            if self.history.item(i).data(Qt.UserRole) == call:
                self.history.takeItem(i)
                break
        item = QListWidgetItem(f"{call}  {name}".strip())
        item.setData(Qt.UserRole, call)
        self.history.insertItem(0, item)
        while self.history.count() > HISTORY:
            self.history.takeItem(self.history.count() - 1)
        show = self.history.count() > 1
        self.hist_label.setVisible(show)
        self.history.setVisible(show)

    # -- buttons --
    def qso_values(self) -> dict:
        d = self._data
        out = {"name": qso_name(d), "qth": qso_qth(d), "gridsquare": (d.get("grid") or "").upper()}
        return {k: v for k, v in out.items() if v}

    def _use(self) -> None:
        if self._data:
            self.use_in_qso.emit({"call": self.call, **self.qso_values()})

    def _open_web(self) -> None:
        if self.call:
            QDesktopServices.openUrl(QUrl(web_url(self.call)))
