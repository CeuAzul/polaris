"""
Auto-atualizacao do POLARIS a partir de GitHub Releases.

Chamado pelo launcher.py ao abrir o app empacotado:
  1. le a versao local (version.py do codigo instalado)
  2. consulta o ultimo Release publicado no repositorio
  3. se a tag do Release for mais nova, baixa o zip do codigo e
     substitui a pasta de codigo de forma ATOMICA

Tudo e a prova de falhas: qualquer erro (sem internet, GitHub fora,
zip corrompido) e engolido e o app abre com o codigo atual. O update
NUNCA deve impedir o app de abrir.

Nao depende de git instalado — usa a API HTTP do GitHub e urllib.
So o CODIGO e substituido; os dados do usuario (config_local, ensaios,
relatorios) ficam em outra pasta (ver config.py) e nao sao tocados.
"""
import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

GITHUB_REPO_PADRAO = "CeuAzul/polaris"
TIMEOUT_S = 6.0
_HEADERS = {"User-Agent": "POLARIS-updater"}


# ============================================================
# COMPARACAO DE VERSAO
# ============================================================
def parse_versao(s) -> tuple:
    """'v1.2.3' / '1.2.3' -> (1, 2, 3). Ignora prefixos/sufixos nao numericos."""
    nums = re.findall(r"\d+", str(s or ""))
    return tuple(int(n) for n in nums) if nums else (0,)


def versao_mais_nova(candidata, base) -> bool:
    """True se 'candidata' > 'base' (comparacao numerica por componente)."""
    return parse_versao(candidata) > parse_versao(base)


def ler_versao_local(app_dir) -> str:
    """Le __version__ do version.py na pasta de codigo instalada."""
    vp = Path(app_dir) / "version.py"
    try:
        txt = vp.read_text(encoding="utf-8")
        m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", txt)
        return m.group(1) if m else "0.0.0"
    except Exception:
        return "0.0.0"


# ============================================================
# CONSULTA AO GITHUB
# ============================================================
def consultar_ultimo_release(repo=GITHUB_REPO_PADRAO, timeout=TIMEOUT_S, abridor=None):
    """Retorna {'tag':..., 'zipball_url':...} do ultimo Release, ou None em erro."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", **_HEADERS,
    })
    try:
        opener = abridor or urllib.request.urlopen
        with opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    tag = data.get("tag_name")
    if not tag:
        return None
    return {"tag": tag, "zipball_url": data.get("zipball_url")}


# ============================================================
# DOWNLOAD + TROCA ATOMICA
# ============================================================
def _achar_raiz_codigo(pasta):
    """O zipball do GitHub extrai numa subpasta unica (repo-sha/).
    Retorna a pasta que contem app.py, ou None."""
    pasta = Path(pasta)
    if (pasta / "app.py").exists():
        return pasta
    subs = [p for p in pasta.iterdir() if p.is_dir()]
    for s in subs:
        if (s / "app.py").exists():
            return s
    if len(subs) == 1:   # zip aninhado mais fundo
        return _achar_raiz_codigo(subs[0])
    return None


def baixar_e_extrair(url, destino, timeout=TIMEOUT_S, abridor=None) -> bool:
    """Baixa o zip de 'url' e substitui a pasta 'destino' de forma atomica.

    'destino' deve conter APENAS codigo (dados do usuario ficam noutra
    pasta), pois e substituido por completo. Retorna True se atualizou.
    """
    destino = Path(destino)
    tmp_root = Path(tempfile.mkdtemp(prefix="polaris_upd_"))
    try:
        zip_path = tmp_root / "codigo.zip"
        opener = abridor or urllib.request.urlopen
        req = urllib.request.Request(url, headers=_HEADERS)
        with opener(req, timeout=timeout) as resp, open(zip_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        extra_dir = tmp_root / "extraido"
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extra_dir)

        raiz = _achar_raiz_codigo(extra_dir)
        if raiz is None:
            return False  # zip sem app.py -> aborta, mantem o codigo atual

        # troca atomica: monta ao lado, renomeia, remove o antigo
        novo = destino.parent / (destino.name + ".novo")
        antigo = destino.parent / (destino.name + ".old")
        shutil.rmtree(novo, ignore_errors=True)
        shutil.rmtree(antigo, ignore_errors=True)
        shutil.move(str(raiz), str(novo))
        if destino.exists():
            os.replace(destino, antigo)
        os.replace(novo, destino)
        shutil.rmtree(antigo, ignore_errors=True)
        return True
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ============================================================
# ORQUESTRACAO
# ============================================================
def atualizar_se_novo(app_dir, repo=GITHUB_REPO_PADRAO, abridor=None) -> tuple:
    """Checa e aplica atualizacao se houver Release mais novo.

    Retorna (atualizou: bool, versao_final: str). Nunca levanta excecao.
    """
    versao_local = ler_versao_local(app_dir)
    try:
        info = consultar_ultimo_release(repo, abridor=abridor)
        if not info or not versao_mais_nova(info["tag"], versao_local):
            return False, versao_local
        if not info.get("zipball_url"):
            return False, versao_local
        ok = baixar_e_extrair(info["zipball_url"], app_dir, abridor=abridor)
        return (ok, ler_versao_local(app_dir) if ok else versao_local)
    except Exception:
        return False, versao_local
