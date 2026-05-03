"""
Analisador de sweep MANUAL.

Substitui o sweep automatico (que dependeria de comando do ESC).
Le um CSV onde o operador subiu o throttle manualmente em degraus,
detecta automaticamente os patamares estaveis e gera a tabela de
pontos do sweep com todas as grandezas derivadas.

Uso tipico:
    df = pd.read_csv(...)  # deve ter colunas t_s, empuxo_g, torque_Nm, rpm
    pontos = extrair_sweep(df, helice_diametro_in=16, rho=1.18,
                            braco_m=0.07)
"""
import math

import numpy as np
import pandas as pd

from .stable_detector import detectar_patamares
from .derived import (
    potencia_mecanica_W,
    coeficientes,
    empuxo_especifico_g_por_W,
    polegadas_para_m,
)
from config import GRAVIDADE


def extrair_sweep(df: pd.DataFrame,
                  helice_diametro_in: float = 16.0,
                  rho: float = 1.225,
                  janela_s: float = 2.0,
                  limiar_rel: float = 0.03,
                  min_dur_s: float = 1.5,
                  coluna_estabilidade: str = "empuxo_g",
                  margem_borda_s: float = 0.4) -> pd.DataFrame:
    """
    Detecta patamares estaveis no CSV e calcula a tabela do sweep.

    Parametros:
        df: dataframe com colunas obrigatorias:
            t_s, empuxo_g, forca_torque_g, rpm
        helice_diametro_in: diametro da helice em polegadas
        rho: densidade do ar (kg/m^3)
        janela_s, limiar_rel, min_dur_s: parametros do detector
        coluna_estabilidade: qual coluna usar para detectar patamar
                             (default empuxo_g; rpm tambem e bom)
        margem_borda_s: descarta esse tempo nas bordas do patamar
                        (transitorios)

    Retorna DataFrame com uma linha por patamar e colunas:
        idx, t_ini, t_fim, dur_s,
        empuxo_g, empuxo_g_std, empuxo_N,
        forca_torque_g, forca_torque_g_std,
        torque_Nm, 
        rpm, rpm_std,
        p_mec_W, T_por_P_g_por_W,
        C_T, C_P, C_Q, FOM
    """
    # ----- validacao de colunas -----
    colunas_req = ["t_s", "empuxo_g", "forca_torque_g", "rpm"]
    falta = [c for c in colunas_req if c not in df.columns]
    if falta:
        raise ValueError(f"CSV sem as colunas: {falta}")

    t = df["t_s"].to_numpy()
    sinal = df[coluna_estabilidade].to_numpy()

    pats = detectar_patamares(t, sinal,
                              janela_s=janela_s,
                              limiar_rel=limiar_rel,
                              min_dur_s=min_dur_s)

    if not pats:
        return pd.DataFrame()

    D_m = polegadas_para_m(helice_diametro_in)
    linhas = []

    for k, p in enumerate(pats, start=1):
        # remove margem das bordas para evitar transitorios
        t_ini = p["t_ini"] + margem_borda_s
        t_fim = p["t_fim"] - margem_borda_s
        if t_fim <= t_ini:
            t_ini = p["t_ini"]
            t_fim = p["t_fim"]

        m = (df["t_s"] >= t_ini) & (df["t_s"] <= t_fim)
        if not m.any():
            continue

        emp = df.loc[m, "empuxo_g"]
        tor = df.loc[m, "forca_torque_g"]
        rpm = df.loc[m, "rpm"]

        emp_med = float(emp.mean()); emp_std = float(emp.std())
        tor_med = float(tor.mean()); tor_std = float(tor.std())
        rpm_med = float(rpm.mean()); rpm_std = float(rpm.std())

        emp_N = (emp_med / 1000.0) * GRAVIDADE
        tor_N = (tor_med / 1000.0) * GRAVIDADE

        # braco: tenta extrair do dataframe, senao default
        braco_m = float(df["braco_m"].iloc[0]) if "braco_m" in df.columns else 0.07
        torque_Nm = tor_N * braco_m

        p_mec = potencia_mecanica_W(rpm_med, tor_med, braco_m)
        TP = empuxo_especifico_g_por_W(emp_med, p_mec)
        coefs = coeficientes(emp_med, tor_med, rpm_med, D_m, rho, braco_m)

        linhas.append({
            "idx": k,
            "t_ini": p["t_ini"],
            "t_fim": p["t_fim"],
            "dur_s": p["dur_s"],
            "empuxo_g": emp_med,
            "empuxo_g_std": emp_std,
            "empuxo_N": emp_N,
            "forca_torque_g": tor_med,
            "forca_torque_g_std": tor_std,
            "torque_Nm": torque_Nm,
            "rpm": rpm_med,
            "rpm_std": rpm_std,
            "p_mec_W": p_mec,
            "T_por_P_g_por_W": TP,
            "C_T": coefs["C_T"],
            "C_P": coefs["C_P"],
            "C_Q": coefs["C_Q"],
            "FOM": coefs["FOM"],
        })

    return pd.DataFrame(linhas)