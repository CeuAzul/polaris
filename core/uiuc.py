"""
Parser do UIUC Propeller Database.

Os arquivos do banco UIUC tem dois tipos relevantes para nos:

    1. arquivos *_static_*.txt   -- ensaios estaticos (J = 0)
       Formato:
           RPM       CT          CP
           1500      0.123       0.045
           ...

    2. arquivos PER3_<helice>.dat (APC) -- modelos analiticos do APC
       (formato diferente, multipla velocidade de avanco)

Aqui usamos primariamente os arquivos _static_ pois nosso ensaio e
estatico (J=0). Cada arquivo cobre uma helice especifica.

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


def listar_helices(uiuc_dir):
    """
    Vasculha o diretorio do UIUC e retorna lista de helices disponiveis
    (apenas as com dados estaticos).

    Retorna lista de dicts: {nome, fabricante, diametro_in, passo_in, arquivo_static}
    """
    uiuc_dir = Path(uiuc_dir)
    if not uiuc_dir.exists():
        return []

    helices = []
    # padrao tipico: "apce_16x8_static_..." ou "apc_16x8_static_..."
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


def buscar_helice(uiuc_dir, diametro_in, passo_in, fabricante=None, tol=0.5):
    """
    Procura uma helice no banco com o diametro e passo dados (com tolerancia).
    Se fabricante for None, retorna a primeira encontrada.
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


def carregar_helice(uiuc_dir, diametro_in, passo_in, fabricante=None, tol=0.5):
    """
    Carrega CT/CP estatico de uma helice. Retorna (info_dict, dataframe) ou (None, None).
    """
    h = buscar_helice(uiuc_dir, diametro_in, passo_in, fabricante, tol)
    if not h:
        return None, None
    df = _parse_arquivo_static(h["arquivo_static"])
    return h, df


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
        # interpola CT/CP do UIUC nesse RPM
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
