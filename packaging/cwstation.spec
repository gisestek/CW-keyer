# PyInstaller spec for CW Station.  Build:  pyinstaller --noconfirm packaging/cwstation.spec
# Produces dist/CWStation/ (one-folder build: fast start, easy to inspect).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
MODEL = ROOT / "third_party" / "deepcw-engine"
if not (MODEL / "model.onnx").exists():
    raise SystemExit(f"DeepCW model missing: {MODEL / 'model.onnx'}")

datas = [
    (str(ROOT / "cwstation" / "i18n"), "cwstation/i18n"),
    (str(MODEL / "model.onnx"), "models/deepcw-engine"),
    (str(MODEL / "model.onnx.json"), "models/deepcw-engine"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "README.md"), "."),
]
if (MODEL / "LICENSE").exists():
    datas.append((str(MODEL / "LICENSE"), "models/deepcw-engine"))
datas += collect_data_files("_sounddevice_data")
datas += collect_data_files("_soundfile_data")
datas += collect_data_files("onnxruntime")
binaries = collect_dynamic_libs("onnxruntime") + collect_dynamic_libs("soxr")
hiddenimports = collect_submodules("websockets") + ["soxr", "sounddevice", "soundfile"]

excludes = [
    "tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtPdf", "PySide6.QtQuick3D", "PySide6.QtSql", "PySide6.QtBluetooth", "PySide6.QtLocation",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CWStation",
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CWStation")
