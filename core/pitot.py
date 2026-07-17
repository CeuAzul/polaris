"""
Tubo de Pitot (sensor de pressao diferencial MS4525DO).

Modelo de medicao:
    q [Pa] = (raw - raw_offset) * pa_per_count        # pressao dinamica
    V [m/s] = sqrt(2 * q / rho)                        # incompressivel

Onde:
    raw         : contagem bruta do sensor (14 bits, 0..16383)
    raw_offset  : tara do sensor (medida quando q=0, sem fluxo)
    pa_per_count: sensibilidade em Pa por contagem, depende do
                  range do sensor e do tipo (A ou B).

MS4525DO-DS3BI001DP (variante mais comum em Aerodesign):
    Range: +/- 1 psi = +/- 6894.76 Pa
    Tipo B: 5%-95% (raw_min=819, raw_max=15565)
    pa_per_count = 2 * 6894.76 / (15565 - 819) ~= 0.9352

MS4525DO-DS3AI001DP (Tipo A, 10%-90%):
    pa_per_count = 2 * 6894.76 / (14746 - 1638) ~= 1.0520

A calibracao tambem suporta um fator k_corr (default 1.0) para
correcao empirica contra anemometro de referencia.

Cada calibracao salva tem hash SHA-1 (cal_id) para rastreabilidade
analoga as celulas de empuxo/torque.
"""
import json
import math
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

import numpy as np


# Sentinelas do firmware
PITOT_OK       = 0
PITOT_RESERVED = 1
PITOT_STALE    = 2
PITOT_FAULT    = 3
PITOT_AUSENTE  = 4

# Defaults para o MS4525DO-DS3BI001DP (+/-1 psi, Tipo B)
MS4525_RANGE_PA_DEFAULT = 6894.76
MS4525_PA_PER_COUNT_DEFAULT = 2.0 * MS4525_RANGE_PA_DEFAULT / (15565.0 - 819.0)


# ============================================================
# MODELO DE CALIBRACAO
# ============================================================
@dataclass
class PitotCalibracao:
    """Calibracao do Pitot. Modelo: q[Pa] = (raw - offset) * pa_per_count * k_corr."""
    sensor: str = "MS4525DO-DS3BI001DP"
    range_pa: float = MS4525_RANGE_PA_DEFAULT
    pa_per_count: float = MS4525_PA_PER_COUNT_DEFAULT
    raw_offset: float = 8192.0       # contagem em q=0 (tara)
    k_corr: float = 1.0              # correcao empirica vs anemometro
    n_amostras_tara: int = 0
    desvio_tara: float = 0.0
    data_offset: str = ""
    cal_id: str = ""

    def aplicar_pa(self, raw: float, status: int = PITOT_OK) -> float:
        """Converte raw -> Pa. Retorna 0 se sensor ausente/falha."""
        if status >= PITOT_FAULT:
            return 0.0
        return float((raw - self.raw_offset) * self.pa_per_count * self.k_corr)

    def aplicar_velocidade(self, raw: float, rho: float, status: int = PITOT_OK) -> float:
        """Converte raw -> V [m/s] usando rho do ar atual."""
        if status >= PITOT_FAULT or rho <= 0:
            return 0.0
        q = self.aplicar_pa(raw, status)
        # q pode ser ligeiramente negativo por ruido proximo de zero;
        # nesse caso retorna 0 (V negativa nao faz sentido fisico).
        if q <= 0:
            return 0.0
        return math.sqrt(2.0 * q / rho)

    def gerar_id(self) -> str:
        content = (
            f"{self.sensor}|{self.range_pa:.2f}|{self.pa_per_count:.6f}|"
            f"{self.raw_offset:.2f}|{self.k_corr:.6f}|{self.data_offset}"
        )
        h = hashlib.sha1(content.encode()).hexdigest()[:10]
        self.cal_id = h
        return h

    def qualidade(self) -> str:
        if self.n_amostras_tara < 5:
            return "Sem tara"
        # desvio_tara muito alto sugere ruido eletrico ou sensor instavel
        if self.desvio_tara > 5.0:   # 5 contagens ~ 5 Pa ~ 2.8 m/s @ 1.2 kg/m^3 (ja e ruim)
            return "Ruim"
        if self.desvio_tara > 2.0:
            return "Atencao"
        return "OK"


def carregar_pitot_cal(path) -> PitotCalibracao:
    if not Path(path).exists():
        return PitotCalibracao()
    try:
        with open(path) as f:
            d = json.load(f)
        return PitotCalibracao(**d)
    except Exception:
        return PitotCalibracao()


def salvar_pitot_cal(path, cal: PitotCalibracao):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cal.gerar_id()
    with open(path, "w") as f:
        json.dump(asdict(cal), f, indent=2, ensure_ascii=False)


# ============================================================
# CONVERSAO DIRETA (sem objeto)
# ============================================================
def pa_de_raw(raw: float, raw_offset: float = 8192.0,
              pa_per_count: float = MS4525_PA_PER_COUNT_DEFAULT,
              k_corr: float = 1.0) -> float:
    """Converte raw count -> pressao dinamica (Pa)."""
    return float((raw - raw_offset) * pa_per_count * k_corr)


def velocidade_de_pa(q_pa: float, rho: float) -> float:
    """V [m/s] = sqrt(2 q / rho). Para q<=0 retorna 0."""
    if q_pa <= 0 or rho <= 0:
        return 0.0
    return math.sqrt(2.0 * q_pa / rho)


def velocidade_de_raw(raw: float, rho: float,
                      raw_offset: float = 8192.0,
                      pa_per_count: float = MS4525_PA_PER_COUNT_DEFAULT,
                      k_corr: float = 1.0) -> float:
    """raw -> V [m/s] em uma chamada. Conveniencia para vetorizacao."""
    q = pa_de_raw(raw, raw_offset, pa_per_count, k_corr)
    return velocidade_de_pa(q, rho)


# ============================================================
# TARA (calculo de raw_offset a partir de uma serie de amostras)
# ============================================================
def calcular_tara(amostras_raw, status_amostras=None) -> tuple:
    """
    Recebe amostras raw com Pitot parado (q=0) e calcula offset + ruido.

    Filtra amostras com status != OK. Se nao houver amostras validas,
    retorna (0.0, 0.0, 0).

    Retorna: (offset_medio, desvio_padrao, n_validas)
    """
    arr = np.asarray(amostras_raw, dtype=float)
    if status_amostras is not None:
        st = np.asarray(status_amostras, dtype=int)
        validas = st == PITOT_OK
        arr = arr[validas]
    n = len(arr)
    if n == 0:
        return 0.0, 0.0, 0
    return float(np.mean(arr)), float(np.std(arr)), n


# ============================================================
# UTIL
# ============================================================
def status_legivel(status: int) -> str:
    return {
        PITOT_OK:       "ok",
        PITOT_RESERVED: "reservado",
        PITOT_STALE:    "stale",
        PITOT_FAULT:    "fault",
        PITOT_AUSENTE:  "ausente",
    }.get(int(status), f"desconhecido({status})")
