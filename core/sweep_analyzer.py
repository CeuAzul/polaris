"""
Analisador de sweep MANUAL.

Substitui o sweep automatico (que dependeria de comando do ESC).
Le um CSV onde o operador subiu o throttle manualmente em degraus,
detecta automaticamente os patamares estaveis e gera a tabela de
pontos do sweep com todas as grandezas derivadas.

Em modo dinamico (CSV com coluna velocidade_ms), tambem exige
estabilidade da velocidade do tunel para validar um patamar, e
calcula J e eta para cada ponto.

Uso tipico:
    df = pd.read_csv(...)  # deve ter colunas t_s, empuxo_g, torque_Nm, rpm
    pontos = extrair_sweep(df, helice_diametro_in=16, rho=1.18,
                            braco_m=0.07)
"""
import math

import numpy as np
import pandas as pd

from .stable_detector import (
    detectar_patamares,
    mascara_estavel,
    patamares_a_partir_de_mascara,
)
from .derived import (
    potencia_mecanica_W,
    coeficientes,
    empuxo_especifico_g_por_W,
    polegadas_para_m,
    LIMIAR_DINAMICO_MS,
)
from config import GRAVIDADE


def extrair_sweep(df: pd.DataFrame,
                  helice_diametro_in: float = 16.0,
                  rho: float = 1.225,
                  janela_s: float = 2.0,
                  limiar_rel: float = 0.03,
                  min_dur_s: float = 1.5,
                  coluna_estabilidade: str = "empuxo_g",
                  margem_borda_s: float = 0.4,
                  exigir_velocidade_estavel: bool = True,
                  limiar_rel_V: float = 0.05) -> pd.DataFrame:
    """
    Detecta patamares estaveis no CSV e calcula a tabela do sweep.

    Parametros:
        df: dataframe com colunas obrigatorias:
            t_s, empuxo_g, forca_torque_g, rpm
            (opcionalmente velocidade_ms para modo dinamico)
        helice_diametro_in: diametro da helice em polegadas
        rho: densidade do ar (kg/m^3)
        janela_s, limiar_rel, min_dur_s: parametros do detector
        coluna_estabilidade: qual coluna usar para detectar patamar
                             (default empuxo_g; rpm tambem e bom)
        margem_borda_s: descarta esse tempo nas bordas do patamar
        exigir_velocidade_estavel: se True e a coluna velocidade_ms
            existir, exige V tambem estavel (interseccao das mascaras)
        limiar_rel_V: tolerancia relativa para V (mais frouxa que T/Q
            porque vento de tunel oscila mais)

    Retorna DataFrame com uma linha por patamar e colunas estaticas:
        idx, t_ini, t_fim, dur_s,
        empuxo_g, empuxo_g_std, empuxo_N,
        forca_torque_g, forca_torque_g_std, torque_Nm,
        rpm, rpm_std,
        p_mec_W, T_por_P_g_por_W,
        C_T, C_P, C_Q, FOM

    E, se houver velocidade_ms no CSV, tambem:
        V_med, V_std, q_med, J, eta
    """
    # ----- validacao de colunas -----
    colunas_req = ["t_s", "empuxo_g", "forca_torque_g", "rpm"]
    falta = [c for c in colunas_req if c not in df.columns]
    if falta:
        raise ValueError(f"CSV sem as colunas: {falta}")

    t = df["t_s"].to_numpy()
    sinal = df[coluna_estabilidade].to_numpy()

    tem_pitot = "velocidade_ms" in df.columns
    usa_dinamico = tem_pitot and exigir_velocidade_estavel

    if usa_dinamico:
        V = df["velocidade_ms"].to_numpy()
        # mascara dupla: sinal-base estavel E velocidade estavel
        m_base = mascara_estavel(t, sinal, janela_s=janela_s,
                                 limiar_rel=limiar_rel,
                                 limiar_min_abs=5.0)
        m_V = mascara_estavel(t, V, janela_s=janela_s,
                              limiar_rel=limiar_rel_V,
                              limiar_min_abs=0.2)  # 0.2 m/s piso
        m_total = m_base & m_V
        pats = patamares_a_partir_de_mascara(t, m_total, sinal=sinal,
                                             min_dur_s=min_dur_s)
    else:
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

        # Velocidade media do patamar (se existir)
        V_med = 0.0
        V_std = 0.0
        q_med = 0.0
        if tem_pitot:
            V_seg = df.loc[m, "velocidade_ms"]
            V_med = float(V_seg.mean())
            V_std = float(V_seg.std())
            if "pressao_dinamica_pa" in df.columns:
                q_med = float(df.loc[m, "pressao_dinamica_pa"].mean())
            else:
                q_med = 0.5 * rho * V_med * V_med

        coefs = coeficientes(emp_med, tor_med, rpm_med, D_m, rho, braco_m,
                             V_inflow_ms=V_med)

        linha = {
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
        }
        if tem_pitot:
            linha.update({
                "V_med": V_med,
                "V_std": V_std,
                "q_med": q_med,
                "J": coefs["J"],
                "eta": coefs["eta"],
            })
        linhas.append(linha)

    return pd.DataFrame(linhas)
