"""
Analise espectral (FFT) dos sinais de empuxo e torque.

Identifica picos espectrais relacionados a:
    - 1xRPM        : desbalanceamento da helice
    - n_pas * RPM  : frequencia de passagem de pa (BPF)
    - harmonicas

Util para diagnostico estrutural da bancada e da helice.
"""
import numpy as np
import pandas as pd


def fft_sinal(t: np.ndarray, sinal: np.ndarray, remover_dc: bool = True):
    """
    Retorna (frequencias_Hz, magnitude) do sinal.
    """
    t = np.asarray(t, dtype=float)
    s = np.asarray(sinal, dtype=float)
    if len(t) < 8:
        return np.array([]), np.array([])

    # tempo deve ser uniforme; caso nao seja, reamostra
    dt_med = float(np.median(np.diff(t)))
    if dt_med <= 0:
        return np.array([]), np.array([])
    t_uni = np.arange(t[0], t[-1], dt_med)
    s_uni = np.interp(t_uni, t, s)

    if remover_dc:
        s_uni = s_uni - np.mean(s_uni)

    # janela de Hann para reduzir vazamento espectral
    w = np.hanning(len(s_uni))
    s_w = s_uni * w
    fft_vals = np.fft.rfft(s_w)
    freqs = np.fft.rfftfreq(len(s_w), d=dt_med)

    # magnitude normalizada
    mag = np.abs(fft_vals) * 2.0 / np.sum(w)
    return freqs, mag


def picos_esperados(rpm: float, n_pas: int = 2, n_harmonicas: int = 3):
    """
    Retorna dict com frequencias esperadas em Hz para um dado RPM:
        '1xRPM', 'BPF', '2xBPF', etc.
    """
    f_rpm = rpm / 60.0
    out = {"1xRPM": f_rpm}
    f_bpf = f_rpm * n_pas
    for k in range(1, n_harmonicas + 1):
        nome = f"{k}xBPF" if k > 1 else "BPF"
        out[nome] = f_bpf * k
    return out


def encontrar_picos_top(freqs: np.ndarray, mag: np.ndarray, n=5,
                        f_min: float = 5.0, f_max: float = 500.0):
    """
    Retorna os N maiores picos espectrais dentro da faixa [f_min, f_max].
    """
    if len(freqs) == 0:
        return []
    m = (freqs >= f_min) & (freqs <= f_max)
    if not m.any():
        return []
    idxs = np.where(m)[0]
    mags = mag[idxs]
    ord_desc = np.argsort(mags)[::-1]
    selecionados = []
    for i in ord_desc[: n * 4]:
        f = float(freqs[idxs[i]])
        # evita duplicatas proximas (separacao minima de 1 Hz)
        if any(abs(f - p[0]) < 1.0 for p in selecionados):
            continue
        selecionados.append((f, float(mags[i])))
        if len(selecionados) >= n:
            break
    return selecionados
