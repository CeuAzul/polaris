"""
Launcher empacotado do POLARIS (ponto de entrada do POLARIS.exe).

Responsabilidades:
  1. garantir que a pasta de codigo (APP_DIR) exista — na 1a execucao,
     copia a copia embarcada no proprio .exe
  2. checar GitHub Releases e atualizar o codigo automaticamente ao abrir
  3. rodar o app.py (possivelmente atualizado) usando o Python embarcado

Funciona tanto congelado (PyInstaller, sys.frozen=True) quanto solto
(modo dev), caso em que apenas roda o app do proprio repositorio.

Arquitetura "runtime pesado + codigo leve": o .exe carrega o Python e
as bibliotecas grandes (matplotlib/pandas/numpy/...), que quase nunca
mudam; o codigo do POLARIS e atualizado a parte (download de KB).
"""
import os
import shutil
import sys
from pathlib import Path


def _dir_base() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "POLARIS"


def _app_dir() -> Path:
    return _dir_base() / "app"


def _fonte_embarcada() -> Path:
    """Copia do codigo embarcada no .exe (PyInstaller extrai em _MEIPASS)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "app_src"
    return Path(__file__).parent


def _garantir_codigo(app_dir: Path):
    """Na 1a execucao, popula APP_DIR com a copia embarcada no .exe."""
    if (app_dir / "app.py").exists():
        return
    app_dir.mkdir(parents=True, exist_ok=True)
    fonte = _fonte_embarcada()
    if (fonte / "app.py").exists():
        shutil.copytree(fonte, app_dir, dirs_exist_ok=True)


def _rodar_app(app_dir: Path):
    """Importa e roda o app.py de app_dir, com o codigo antigo descarregado."""
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    # descarrega modulos do codigo antigo (caso o updater tenha trocado)
    for m in list(sys.modules):
        if m in ("app", "config", "version") or m.startswith(("core", "gui")):
            del sys.modules[m]
    import app
    app.main()


def main():
    if not getattr(sys, "frozen", False):
        # modo dev: roda o app do proprio repo, sem update
        sys.path.insert(0, str(Path(__file__).parent))
        import app
        app.main()
        return

    app_dir = _app_dir()
    _garantir_codigo(app_dir)

    # auto-update a prova de falhas: nunca impede o app de abrir
    try:
        sys.path.insert(0, str(app_dir))
        from importlib import import_module
        updater = import_module("core.updater")
        updater.atualizar_se_novo(str(app_dir))
    except Exception:
        pass

    _rodar_app(app_dir)


if __name__ == "__main__":
    main()
