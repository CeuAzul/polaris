# -*- mode: python ; coding: utf-8 -*-
"""
Receita do PyInstaller para o POLARIS.

Build (na raiz do repo, com o venv ativo e pyinstaller instalado):
    pyinstaller polaris.spec

Gera dist/POLARIS/ (modo one-folder) com POLARIS.exe.

Estrategia "runtime pesado + codigo leve":
  - o .exe embarca Python + libs grandes (matplotlib/pandas/numpy/...)
  - o codigo do POLARIS vai junto como DADOS em app_src/ (copia inicial);
    o auto-update baixa versoes novas do codigo a parte (ver core/updater)

Se ao rodar aparecer ModuleNotFoundError de alguma lib, acrescente o
nome em hiddenimports abaixo e rebuilde.
"""
from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# --- codigo do POLARIS embarcado como fonte inicial (app_src/) ---
datas = [
    ("app.py", "app_src"),
    ("config.py", "app_src"),
    ("version.py", "app_src"),
    ("README.md", "app_src"),
]
datas += collect_data_files("matplotlib")

hiddenimports = []
hiddenimports += collect_submodules("matplotlib")
hiddenimports += [
    "matplotlib.backends.backend_tkagg",
    "numpy",
    "pandas",
    "reportlab",
    "reportlab.pdfgen",
    "reportlab.lib",
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PyInstaller"],
    noarchive=False,
)

# pastas de codigo do POLARIS como arvore de dados em app_src/
a.datas += Tree("core", prefix="app_src/core", excludes=["__pycache__", "*.pyc"])
a.datas += Tree("gui", prefix="app_src/gui", excludes=["__pycache__", "*.pyc"])
a.datas += Tree("uiuc_data", prefix="app_src/uiuc_data")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="POLARIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # app GUI: sem janela de terminal
    disable_windowed_traceback=False,
    icon="installer/polaris.ico" if __import__("os").path.exists("installer/polaris.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="POLARIS",
)
