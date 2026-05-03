"""Detector de regime estavel (janela movel)."""
from collections import deque
import numpy as np


class StableDetector:
    """Online: detecta janelas onde o sinal de empuxo esta estavel.

    Estavel se desvio padrao da janela (ultimos N segundos) < limiar.
    """

    def __init__(self, janela_s: float = 2.0, limiar_g: float = 20.0):
        self.janela_s = janela_s
        self.limiar_g = limiar_g
        self.buffer = deque()   # (t, valor)

    def update(self, t: float, valor: float):
        self.buffer.append((t, valor))
        while self.buffer and (t - self.buffer[0][0]) > self.janela_s:
            self.buffer.popleft()

        if len(self.buffer) < 5:
            return False, 0.0, 0.0

        valores = np.array([v for _, v in self.buffer])
        media = float(np.mean(valores))
        desvio = float(np.std(valores))
        estavel = desvio < self.limiar_g
        return estavel, media, desvio

    def reset(self):
        self.buffer.clear()


def detectar_patamares(t: np.ndarray, sinal: np.ndarray,
                       janela_s: float = 2.0,
                       limiar_rel: float = 0.03,
                       min_dur_s: float = 1.5,
                       limiar_min_abs: float = 5.0):
    """
    Detector OFFLINE de patamares estaveis. Usado para extrair pontos de
    sweep a partir de um CSV onde o operador subiu o throttle em degraus.

    Algoritmo:
        1. Para cada amostra, calcula desvio padrao numa janela movel.
        2. Marca como "estavel" onde desvio < max(limiar_rel * media, limiar_min_abs).
        3. Agrupa amostras estaveis contiguas em "patamares".
        4. Filtra patamares com duracao menor que min_dur_s.

    Parametros:
        t          : tempos (s)
        sinal      : valor a analisar (ex: empuxo em g)
        janela_s   : tamanho da janela movel
        limiar_rel : limiar relativo (3% da media local por default)
        min_dur_s  : duracao minima de um patamar valido
        limiar_min_abs : piso absoluto do limiar (em unidades do sinal)

    Retorna lista de dicts:
        [{idx_ini, idx_fim, t_ini, t_fim, dur_s, media, desvio}, ...]
    """
    t = np.asarray(t, dtype=float)
    s = np.asarray(sinal, dtype=float)
    n = len(t)
    if n < 10:
        return []

    # passo medio para converter janela em amostras
    dt_med = float(np.median(np.diff(t)))
    if dt_med <= 0:
        return []
    n_jan = max(5, int(round(janela_s / dt_med)))

    # rolling std + rolling mean
    desvio = np.zeros(n)
    media = np.zeros(n)
    for i in range(n):
        a = max(0, i - n_jan // 2)
        b = min(n, i + n_jan // 2 + 1)
        seg = s[a:b]
        media[i] = np.mean(seg)
        desvio[i] = np.std(seg)

    # mascara estavel
    limiar_local = np.maximum(np.abs(media) * limiar_rel, limiar_min_abs)
    estavel = desvio < limiar_local

    # agrupa contiguos
    patamares = []
    i = 0
    while i < n:
        if estavel[i]:
            j = i
            while j + 1 < n and estavel[j + 1]:
                j += 1
            dur = t[j] - t[i]
            if dur >= min_dur_s:
                patamares.append({
                    "idx_ini": int(i),
                    "idx_fim": int(j),
                    "t_ini": float(t[i]),
                    "t_fim": float(t[j]),
                    "dur_s": float(dur),
                    "media": float(np.mean(s[i:j + 1])),
                    "desvio": float(np.std(s[i:j + 1])),
                })
            i = j + 1
        else:
            i += 1

    return patamares
