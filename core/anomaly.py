"""
Detector de anomalias durante coleta.

Heuristicas:
    - Empuxo cai significativamente enquanto RPM esta alto (helice danificada/descolando).
    - Torque pico anormal sem aumento correspondente de empuxo (stall).
    - RPM oscila muito com throttle estavel (problema mecanico/eletrico).

Usa janelas de tempo curtas (~5 s) para detectar mudancas bruscas em relacao
a um baseline movel.
"""
from collections import deque
import numpy as np

from config import (
    ANOMALIA_QUEDA_EMPUXO_PCT,
    ANOMALIA_PICO_TORQUE_PCT,
    ANOMALIA_VARIACAO_RPM_PCT,
)


class AnomalyDetector:
    """
    Mantem dois buffers: 'baseline' (~10s) e 'curto' (~1s).
    Detecta quando os valores curtos divergem demais do baseline.
    """

    def __init__(self, janela_baseline_s: float = 10.0, janela_curto_s: float = 1.0):
        self.j_base = janela_baseline_s
        self.j_curto = janela_curto_s
        self.buf = deque()         # (t, emp_g, tor_g, rpm)
        self.eventos = []          # lista de (t, descricao)
        self._ultimo_evento_t = -10.0
        self._cooldown_s = 3.0     # nao gera o mesmo evento varias vezes seguidas

    def reset(self):
        self.buf.clear()
        self.eventos.clear()

    def update(self, t: float, emp_g: float, tor_g: float, rpm: float):
        """Retorna lista de novos eventos detectados nesta amostra."""
        self.buf.append((t, emp_g, tor_g, rpm))
        # remove velhos do buffer baseline
        while self.buf and (t - self.buf[0][0]) > self.j_base:
            self.buf.popleft()

        if len(self.buf) < 20:
            return []

        # split em base e curto
        arr = np.array(self.buf)
        ts = arr[:, 0]
        mask_curto = ts >= (t - self.j_curto)
        mask_base = ts < (t - self.j_curto)

        if mask_curto.sum() < 3 or mask_base.sum() < 10:
            return []

        emp_base = float(np.mean(arr[mask_base, 1]))
        tor_base = float(np.mean(arr[mask_base, 2]))
        rpm_base = float(np.mean(arr[mask_base, 3]))

        emp_atual = float(np.mean(arr[mask_curto, 1]))
        tor_atual = float(np.mean(arr[mask_curto, 2]))
        rpm_atual = float(np.mean(arr[mask_curto, 3]))
        rpm_std_atual = float(np.std(arr[mask_curto, 3]))

        novos = []
        if (t - self._ultimo_evento_t) < self._cooldown_s:
            return novos

        # 1) queda subita de empuxo com RPM alto mantido
        if emp_base > 100 and rpm_base > 1000:
            queda_pct = (emp_base - emp_atual) / emp_base * 100.0
            if queda_pct > ANOMALIA_QUEDA_EMPUXO_PCT:
                novos.append((t, f"Queda de empuxo {queda_pct:.0f}% (poss. dano na helice)"))

        # 2) pico de torque desacompanhado de empuxo
        if tor_base > 50 and emp_base > 50:
            torque_subiu_pct = (tor_atual - tor_base) / tor_base * 100.0
            empuxo_subiu_pct = (emp_atual - emp_base) / emp_base * 100.0
            if torque_subiu_pct > ANOMALIA_PICO_TORQUE_PCT and empuxo_subiu_pct < 5:
                novos.append((t, f"Torque subiu {torque_subiu_pct:.0f}% sem empuxo (stall?)"))

        # 3) RPM oscilando muito
        if rpm_base > 1000:
            osc_pct = rpm_std_atual / rpm_base * 100.0
            if osc_pct > ANOMALIA_VARIACAO_RPM_PCT:
                novos.append((t, f"RPM oscilando {osc_pct:.0f}% (problema mecanico/ESC)"))

        if novos:
            self.eventos.extend(novos)
            self._ultimo_evento_t = t

        return novos
