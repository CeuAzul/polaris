"""
Parser do UIUC Propeller Database.

Os arquivos do banco UIUC tem dois tipos relevantes para nos:

    1. arquivos *_static_*.txt   -- ensaios estaticos (J = 0)
       Formato:
           RPM       CT          CP
           1500      0.123       0.045
           ...

    2. arquivos *_<rpm>.txt      -- ensaios dinamicos (J > 0)
       Formato:
           J         CT      CP        eta
           0.000     0.123   0.045     0.000
           0.100     0.121   0.046     0.263
           ...
       Nome contem o RPM nominal: e.g. apce_16x8_2500.txt
       Excluem-se arquivos *_static_* e *_geom*.

Convenção de nome esperada (UIUC): apce_16x8_static_2780rd.txt etc.
Recomenda-se baixar do site oficial https://m-selig.ae.illinois.edu/props/
e colocar tudo em uiuc_data/.
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd


def _parse_arquivo_static(path):
    """
    Le um arquivo *_static_*.txt do UIUC.
    Retorna DataFrame com colunas: RPM, CT, CP, Re (se tiver).
    """
    path = Path(path)
    linhas = []
    with open(path) as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            # ignora cabecalhos com letras
            if re.search(r"[A-Za-z]", linha):
                continue
            partes = linha.split()
            if len(partes) >= 3:
                try:
                    vals = [float(x) for x in partes]
                    linhas.append(vals)
                except ValueError:
                    continue

    if not linhas:
        return pd.DataFrame()

    n_cols = max(len(r) for r in linhas)
    cols = ["RPM", "CT", "CP", "Re"][:n_cols]
    arr = np.array([r + [np.nan] * (n_cols - len(r)) for r in linhas])
    return pd.DataFrame(arr, columns=cols)


def _parse_arquivo_dinamico(path):
    """
    Le um arquivo dinamico do UIUC (curva J vs CT/CP/eta para RPM fixo).

    Retorna DataFrame com colunas J, CT, CP, eta (eta opcional).
    """
    path = Path(path)
    linhas = []
    with open(path) as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            if re.search(r"[A-Za-z]", linha):
                continue
            partes = linha.split()
            if len(partes) >= 3:
                try:
                    vals = [float(x) for x in partes]
                    linhas.append(vals)
                except ValueError:
                    continue

    if not linhas:
        return pd.DataFrame()

    n_cols = max(len(r) for r in linhas)
    cols = ["J", "CT", "CP", "eta"][:n_cols]
    arr = np.array([r + [np.nan] * (n_cols - len(r)) for r in linhas])
    df = pd.DataFrame(arr, columns=cols)

    # Se eta nao veio, calcula
    if "eta" not in df.columns or df["eta"].isna().all():
        with np.errstate(divide="ignore", invalid="ignore"):
            df["eta"] = np.where(df["CP"] > 0, df["J"] * df["CT"] / df["CP"], 0.0)
    return df


def listar_helices(uiuc_dir):
    """
    Vasculha o diretorio do UIUC e retorna lista de helices disponiveis
    para ensaio ESTATICO (apenas as com dados *_static_*.txt).

    Retorna lista de dicts: {nome, fabricante, diametro_in, passo_in, arquivo_static}
    """
    uiuc_dir = Path(uiuc_dir)
    if not uiuc_dir.exists():
        return []

    helices = []
    rx = re.compile(
        r"^(?P<fab>[a-zA-Z]+)_(?P<diam>\d+(?:\.\d+)?)x(?P<passo>\d+(?:\.\d+)?)_static",
        re.IGNORECASE,
    )

    for path in sorted(uiuc_dir.rglob("*_static*.txt")):
        m = rx.match(path.name)
        if not m:
            continue
        helices.append({
            "nome": f"{m.group('fab').upper()} {m.group('diam')}x{m.group('passo')}",
            "fabricante": m.group("fab").upper(),
            "diametro_in": float(m.group("diam")),
            "passo_in": float(m.group("passo")),
            "arquivo_static": str(path),
        })
    return helices


def listar_helices_dinamicas(uiuc_dir):
    """
    Vasculha o diretorio e retorna lista de helices que tem arquivos
    dinamicos (curvas J/CT/CP por RPM).

    Cada item agrega TODOS os RPMs disponiveis para uma helice:
        {nome, fabricante, diametro_in, passo_in, arquivos: [(rpm, path), ...]}
    """
    uiuc_dir = Path(uiuc_dir)
    if not uiuc_dir.exists():
        return []

    # nome tipico: apce_16x8_2500.txt (apce_<diam>x<passo>_<rpm>.txt)
    rx = re.compile(
        r"^(?P<fab>[a-zA-Z]+)_(?P<diam>\d+(?:\.\d+)?)x(?P<passo>\d+(?:\.\d+)?)_(?P<rpm>\d{3,5})\.txt$",
        re.IGNORECASE,
    )

    grupos = {}
    for path in sorted(uiuc_dir.rglob("*.txt")):
        nome_arq = path.name.lower()
        if "_static" in nome_arq or "_geom" in nome_arq:
            continue
        m = rx.match(path.name)
        if not m:
            continue
        chave = (m.group("fab").upper(), float(m.group("diam")), float(m.group("passo")))
        rpm = float(m.group("rpm"))
        grupos.setdefault(chave, []).append((rpm, str(path)))

    helices = []
    for (fab, diam, passo), arquivos in grupos.items():
        arquivos.sort(key=lambda x: x[0])
        helices.append({
            "nome": f"{fab} {diam}x{passo}",
            "fabricante": fab,
            "diametro_in": diam,
            "passo_in": passo,
            "arquivos": arquivos,
        })
    return helices


def buscar_helice(uiuc_dir, diametro_in, passo_in, fabricante=None, tol=0.5):
    """
    Procura uma helice no banco com o diametro e passo dados (com tolerancia).
    Se fabricante for None, retorna a primeira encontrada.
    Busca apenas arquivos estaticos.
    """
    candidatos = listar_helices(uiuc_dir)
    melhor = None
    menor_dist = float("inf")
    for h in candidatos:
        dd = abs(h["diametro_in"] - diametro_in)
        dp = abs(h["passo_in"] - passo_in)
        if dd > tol or dp > tol:
            continue
        if fabricante and fabricante.upper() not in h["fabricante"].upper():
            continue
        dist = dd + dp
        if dist < menor_dist:
            menor_dist = dist
            melhor = h
    return melhor


def buscar_helice_dinamica(uiuc_dir, diametro_in, passo_in, fabricante=None, tol=0.5):
    """Versao dinamica: retorna helice com lista de arquivos por RPM."""
    candidatos = listar_helices_dinamicas(uiuc_dir)
    melhor = None
    menor_dist = float("inf")
    for h in candidatos:
        dd = abs(h["diametro_in"] - diametro_in)
        dp = abs(h["passo_in"] - passo_in)
        if dd > tol or dp > tol:
            continue
        if fabricante and fabricante.upper() not in h["fabricante"].upper():
            continue
        dist = dd + dp
        if dist < menor_dist:
            menor_dist = dist
            melhor = h
    return melhor


def carregar_helice(uiuc_dir, diametro_in, passo_in, fabricante=None, tol=0.5):
    """
    Carrega CT/CP estatico de uma helice. Retorna (info_dict, dataframe) ou (None, None).
    """
    h = buscar_helice(uiuc_dir, diametro_in, passo_in, fabricante, tol)
    if not h:
        return None, None
    df = _parse_arquivo_static(h["arquivo_static"])
    return h, df


def carregar_curva_dinamica(info_dinamico, rpm_alvo: float):
    """
    Dado um dict retornado por buscar_helice_dinamica e um RPM alvo,
    escolhe o arquivo cujo RPM nominal e mais proximo e parseia.

    Retorna (rpm_arquivo, DataFrame J/CT/CP/eta).
    """
    if not info_dinamico or not info_dinamico.get("arquivos"):
        return None, pd.DataFrame()
    arquivos = info_dinamico["arquivos"]
    # acha o RPM mais proximo
    rpm_arr = np.array([r for r, _ in arquivos])
    idx = int(np.argmin(np.abs(rpm_arr - rpm_alvo)))
    rpm_arq, path = arquivos[idx]
    return rpm_arq, _parse_arquivo_dinamico(path)


def comparar_com_ensaio(df_uiuc, df_ensaio):
    """
    Para cada ponto do ensaio, encontra o ponto UIUC mais proximo em RPM
    e calcula desvio percentual de CT e CP.

    Argumentos:
        df_uiuc: DataFrame com RPM, CT, CP (do banco UIUC)
        df_ensaio: DataFrame com colunas rpm, C_T, C_P (do nosso sweep)

    Retorna DataFrame com colunas:
        rpm_ensaio, CT_ensaio, CT_uiuc, CT_dev_pct,
        CP_ensaio, CP_uiuc, CP_dev_pct
    """
    if df_uiuc.empty or df_ensaio.empty:
        return pd.DataFrame()

    rpm_u = df_uiuc["RPM"].to_numpy()
    ct_u = df_uiuc["CT"].to_numpy()
    cp_u = df_uiuc["CP"].to_numpy()

    linhas = []
    for _, r in df_ensaio.iterrows():
        rpm = float(r["rpm"])
        if rpm <= 0:
            continue
        if rpm < rpm_u.min() or rpm > rpm_u.max():
            ct_ref = np.nan
            cp_ref = np.nan
        else:
            ct_ref = float(np.interp(rpm, rpm_u, ct_u))
            cp_ref = float(np.interp(rpm, rpm_u, cp_u))

        ct_e = float(r["C_T"]); cp_e = float(r["C_P"])
        dev_ct = (ct_e - ct_ref) / ct_ref * 100.0 if ct_ref else np.nan
        dev_cp = (cp_e - cp_ref) / cp_ref * 100.0 if cp_ref else np.nan

        linhas.append({
            "rpm_ensaio": rpm,
            "CT_ensaio": ct_e,
            "CT_uiuc": ct_ref,
            "CT_dev_pct": dev_ct,
            "CP_ensaio": cp_e,
            "CP_uiuc": cp_ref,
            "CP_dev_pct": dev_cp,
        })
    return pd.DataFrame(linhas)


def comparar_dinamico_com_ensaio(df_uiuc, df_ensaio):
    """
    Comparacao em modo dinamico: interpola CT/CP/eta do UIUC no J de cada
    ponto do ensaio.

    Argumentos:
        df_uiuc: DataFrame com J, CT, CP (idealmente eta) - de um arquivo
                 de RPM proximo ao do ensaio.
        df_ensaio: DataFrame com colunas J, C_T, C_P, eta.

    Retorna DataFrame com colunas:
        J_ensaio, CT_ensaio, CT_uiuc, CT_dev_pct,
        CP_ensaio, CP_uiuc, CP_dev_pct,
        eta_ensaio, eta_uiuc, eta_dev_pct
    """
    if df_uiuc.empty or df_ensaio.empty:
        return pd.DataFrame()

    J_u = df_uiuc["J"].to_numpy()
    ct_u = df_uiuc["CT"].to_numpy()
    cp_u = df_uiuc["CP"].to_numpy()
    eta_u = df_uiuc["eta"].to_numpy() if "eta" in df_uiuc.columns else None

    linhas = []
    for _, r in df_ensaio.iterrows():
        J = float(r.get("J", 0.0))
        if J <= 0:
            continue
        if J < J_u.min() or J > J_u.max():
            ct_ref = np.nan; cp_ref = np.nan; eta_ref = np.nan
        else:
            ct_ref = float(np.interp(J, J_u, ct_u))
            cp_ref = float(np.interp(J, J_u, cp_u))
            eta_ref = float(np.interp(J, J_u, eta_u)) if eta_u is not None else np.nan

        ct_e = float(r["C_T"]); cp_e = float(r["C_P"])
        eta_e = float(r.get("eta", 0.0))

        dev_ct = (ct_e - ct_ref) / ct_ref * 100.0 if ct_ref else np.nan
        dev_cp = (cp_e - cp_ref) / cp_ref * 100.0 if cp_ref else np.nan
        dev_eta = (eta_e - eta_ref) / eta_ref * 100.0 if (
            isinstance(eta_ref, float) and not np.isnan(eta_ref) and eta_ref > 0
        ) else np.nan

        linhas.append({
            "J_ensaio": J,
            "CT_ensaio": ct_e, "CT_uiuc": ct_ref, "CT_dev_pct": dev_ct,
            "CP_ensaio": cp_e, "CP_uiuc": cp_ref, "CP_dev_pct": dev_cp,
            "eta_ensaio": eta_e, "eta_uiuc": eta_ref, "eta_dev_pct": dev_eta,
        })
    return pd.DataFrame(linhas)
