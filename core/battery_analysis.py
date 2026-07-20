"""
Analises da tensao da bateria (segundo Arduino, monitor de celulas).

Trabalha sobre o DataFrame de um CSV de ensaio ja carregado, usando
as colunas gravadas pela aba de Coleta:
    v_bat_total, v_cel1 .. v_cel6

Todas as analises sao feitas SEM corrente (o INA226 ainda nao foi
integrado). Portanto:
  - sag e desbalanceamento sao medidas diretas e confiaveis;
  - o "droop" (V vs P_mec) e um INDICADOR comparativo entre packs,
    NAO a resistencia interna verdadeira (que exigiria corrente).

A tensao e gravada a ~1 Hz com hold-last-value, entao a serie e uma
escadinha comparada a empuxo/RPM (~80 Hz) — suficiente para sag e
desbalanceamento, insuficiente para FFT.
"""
import numpy as np

# Limiares de desbalanceamento entre celulas (V)
IMBALANCE_ATENCAO = 0.10   # sob carga, ja merece atencao
IMBALANCE_ALTO = 0.20      # provavel celula fraca / pack degradando

# Limiares de tensao por celula (LiPo)
V_CEL_BAIXA = 3.5          # sob carga, conservador
V_CEL_CRITICA = 3.3        # abaixo disso e arriscado

# Uma celula so e considerada conectada se atingiu esta tensao
V_CEL_CONECTADA = 2.5
# Piso para considerar uma amostra "com bateria" (linha fresca)
V_TOTAL_MIN = 0.1
# Potencia mecanica minima (W) para um ponto entrar no ajuste de droop
P_MEC_MIN_DROOP = 20.0


def colunas_celulas(df) -> list:
    """Retorna as colunas v_celN presentes no DataFrame, em ordem."""
    return [f"v_cel{i}" for i in range(1, 7) if f"v_cel{i}" in df.columns]


def mascara_valida(df) -> np.ndarray:
    """Booleano por linha: amostras com leitura real de bateria.

    Usa v_bat_total quando disponivel, senao o maior valor entre as
    celulas. Linhas sem bateria (0.0) ficam False.
    """
    n = len(df)
    if "v_bat_total" in df.columns:
        return (df["v_bat_total"].fillna(0).to_numpy() > V_TOTAL_MIN)
    cols = colunas_celulas(df)
    if not cols:
        return np.zeros(n, dtype=bool)
    return (df[cols].fillna(0).to_numpy().max(axis=1) > V_TOTAL_MIN)


def tem_dados_bateria(df) -> bool:
    """True se ha pelo menos 2 amostras com leitura de bateria."""
    if df is None or len(df) == 0:
        return False
    if "v_bat_total" not in df.columns and not colunas_celulas(df):
        return False
    return int(mascara_valida(df).sum()) >= 2


def celulas_conectadas(df, mask=None) -> list:
    """Colunas de celulas que atingiram V_CEL_CONECTADA nas linhas validas."""
    cols = colunas_celulas(df)
    if not cols:
        return []
    if mask is None:
        mask = mascara_valida(df)
    if mask.sum() == 0:
        return []
    sub = df.loc[mask, cols]
    return [c for c in cols if float(sub[c].max()) > V_CEL_CONECTADA]


def serie_desbalanceamento(df, mask, conectadas) -> np.ndarray:
    """ΔV = maior - menor celula, por linha valida. Vetor len == mask.sum()."""
    if len(conectadas) < 2:
        return np.zeros(int(mask.sum()))
    sub = df.loc[mask, conectadas].to_numpy(dtype=float)
    return sub.max(axis=1) - sub.min(axis=1)


def ajuste_droop(v_bat, p_mec):
    """Ajuste linear V_bat = a*P_mec + b sobre pontos com motor carregado.

    Retorna dict {slope_v_por_w, intercepto_v, r2, n} ou None se nao ha
    variacao de potencia suficiente. NAO e resistencia interna: e um
    indicador de afundamento (droop) comparavel entre packs.
    """
    v = np.asarray(v_bat, dtype=float)
    p = np.asarray(p_mec, dtype=float)
    m = np.isfinite(v) & np.isfinite(p) & (p > P_MEC_MIN_DROOP) & (v > V_TOTAL_MIN)
    if m.sum() < 5:
        return None
    v = v[m]; p = p[m]
    if (p.max() - p.min()) < 20.0:   # sem faixa de potencia -> fit sem sentido
        return None
    slope, intercepto = np.polyfit(p, v, 1)
    v_pred = slope * p + intercepto
    ss_res = float(np.sum((v - v_pred) ** 2))
    ss_tot = float(np.sum((v - v.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "slope_v_por_w": float(slope),
        "intercepto_v": float(intercepto),
        "r2": float(r2),
        "n": int(m.sum()),
    }


def resumo_bateria(df) -> dict:
    """Resumo numerico + alertas da bateria. {'tem_dados': False} se ausente."""
    if not tem_dados_bateria(df):
        return {"tem_dados": False}

    mask = mascara_valida(df)
    conectadas = celulas_conectadas(df, mask)

    v_total = (df.loc[mask, "v_bat_total"].to_numpy(dtype=float)
               if "v_bat_total" in df.columns
               else df.loc[mask, conectadas].to_numpy(dtype=float).sum(axis=1))

    v_ini = float(v_total[0])
    v_fim = float(v_total[-1])
    v_max = float(v_total.max())
    v_min = float(v_total.min())
    sag = v_max - v_min

    res = {
        "tem_dados": True,
        "n_celulas": len(conectadas),
        "colunas_celulas": conectadas,
        "v_ini": v_ini,
        "v_fim": v_fim,
        "v_max": v_max,
        "v_min": v_min,
        "sag": sag,
        "alertas": [],
    }

    # --- desbalanceamento ---
    if len(conectadas) >= 2:
        dv = serie_desbalanceamento(df, mask, conectadas)
        res["imbalance_med"] = float(dv.mean())
        res["imbalance_max"] = float(dv.max())

        sub = df.loc[mask, conectadas]
        medias = {c: float(sub[c].mean()) for c in conectadas}
        c_fraca = min(medias, key=medias.get)
        # frequencia com que cada celula e a menor
        arr = sub.to_numpy(dtype=float)
        idx_min = arr.argmin(axis=1)
        frac_menor = float(np.mean(idx_min == conectadas.index(c_fraca)))
        res["celula_fraca"] = c_fraca
        res["celula_fraca_idx"] = int(c_fraca.replace("v_cel", ""))
        res["celula_fraca_media"] = medias[c_fraca]
        res["celula_fraca_frac_menor"] = frac_menor
        res["min_cel_v"] = float(sub.to_numpy(dtype=float).min())

        if res["imbalance_max"] >= IMBALANCE_ALTO:
            res["alertas"].append(
                f"Desbalanceamento alto: ΔV_max = {res['imbalance_max']*1000:.0f} mV "
                f"(celula {res['celula_fraca_idx']} provavelmente fraca)")
        elif res["imbalance_max"] >= IMBALANCE_ATENCAO:
            res["alertas"].append(
                f"Desbalanceamento moderado sob carga: ΔV_max = "
                f"{res['imbalance_max']*1000:.0f} mV")

        if res["min_cel_v"] < V_CEL_CRITICA:
            res["alertas"].append(
                f"Celula chegou a {res['min_cel_v']:.2f} V (CRITICO < {V_CEL_CRITICA})")
        elif res["min_cel_v"] < V_CEL_BAIXA:
            res["alertas"].append(
                f"Celula chegou a {res['min_cel_v']:.2f} V sob carga (< {V_CEL_BAIXA})")

    # --- droop ---
    if "p_mec_W" in df.columns:
        droop = ajuste_droop(
            df.loc[mask, "v_bat_total"].to_numpy(dtype=float)
            if "v_bat_total" in df.columns else v_total,
            df.loc[mask, "p_mec_W"].to_numpy(dtype=float),
        )
        res["droop"] = droop

    return res
