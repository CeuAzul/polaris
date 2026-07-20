"""Leitor serial do Arduino de monitoramento de bateria.

Firmware: bancada_bateria_v4.ino (MUX 16 canais + divisores de tensao).

Protocolo do firmware:
  1. No boot pergunta "Quantas celulas voce quer medir (1-6)?"
  2. Espera um numero via serial
  3. Emite CSV a ~1 Hz: Tempo(ms),Cel1(V),...,CelN(V),Total(V)

Este reader roda em thread separada, responde o prompt do numero de
celulas automaticamente e guarda apenas a ULTIMA leitura valida.
Como a bateria atualiza a 1 Hz e a bancada a ~80 Hz, os consumidores
usam snapshot() e aplicam hold-last-value em cada amostra da bancada.
"""
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import serial

# Idade maxima (s) para considerar a leitura da bateria "fresca"
BAT_IDADE_MAX_S = 5.0
MAX_CELULAS = 6

# Calibracao por celula: faixa esperada do fator de correcao.
# Fora disso, provavel erro de medicao / divisor / celula trocada.
FATOR_MIN_ALERTA = 0.80
FATOR_MAX_ALERTA = 1.20
# Abaixo desta tensao a celula e considerada nao conectada (nao calibravel)
V_MIN_CELULA_CAL = 2.5


class BatteryReader(threading.Thread):
    """
    Le linhas do Arduino da bateria e mantem a ultima leitura:
        (v_celulas[6], v_total, idade_s)

    Celulas nao medidas ficam em 0.0.
    """

    def __init__(self, port, n_celulas, baudrate=9600):
        super().__init__(daemon=True)
        self.port = port
        self.n_celulas = max(1, min(MAX_CELULAS, int(n_celulas)))
        self.baudrate = baudrate
        self._stop_event = threading.Event()
        self._ser = None
        self._lock = threading.Lock()
        self.connected = False
        self.last_error = None
        # ultima leitura valida
        self._t_ultima = 0.0
        self._v_celulas = [0.0] * MAX_CELULAS
        self._v_total = 0.0
        self._n_linhas = 0

    def run(self):
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2.5)   # abrir a porta reseta o Arduino (DTR)
            self._ser.reset_input_buffer()
            # responde o prompt "Quantas celulas voce quer medir (1-6)?"
            self._ser.write(f"{self.n_celulas}\n".encode())
            self.connected = True
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            return

        while not self._stop_event.is_set():
            try:
                line = self._ser.readline().decode(errors="ignore").strip()
                if not line:
                    continue

                partes = line.split(",")
                # linha de dados: tempo_ms + n_celulas tensoes + total
                if len(partes) != self.n_celulas + 2:
                    continue   # prompt, linha truncada ou incompleta
                try:
                    int(partes[0])                        # tempo_ms
                    valores = [float(x) for x in partes[1:]]
                except ValueError:
                    continue   # cabecalho "Tempo(ms),Cel1(V),..." ou lixo

                with self._lock:
                    self._t_ultima = time.time()
                    for i in range(MAX_CELULAS):
                        self._v_celulas[i] = (
                            valores[i] if i < self.n_celulas else 0.0
                        )
                    self._v_total = valores[-1]
                    self._n_linhas += 1
            except (serial.SerialException, OSError) as e:
                self.last_error = str(e)
                break

        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass

    def snapshot(self):
        """Retorna (v_celulas[6], v_total, idade_s) da ultima leitura,
        ou None se nenhuma linha valida chegou ainda."""
        with self._lock:
            if self._n_linhas == 0:
                return None
            idade = time.time() - self._t_ultima
            return list(self._v_celulas), self._v_total, idade

    def stop(self):
        self._stop_event.set()


# ============================================================
# CALIBRACAO POR CELULA (fator de correcao em software)
# ============================================================
# O firmware ja aplica um FATOR_CORRECAO fixo. Esta camada fica ACIMA
# dele: um ajuste fino por celula, regulavel sem reflashar o Arduino.
#   v_corrigida[i] = v_medida[i] * fator[i]
#   fator[i]       = V_referencia[i] / V_medida[i]   (multimetro)
#
# Salva em JSON com cal_id (SHA-1) para rastreabilidade, analogo ao
# Pitot e as celulas de empuxo/torque.
@dataclass
class BateriaCalibracao:
    """Fatores de correcao por celula. Default 1.0 = sem correcao."""
    fatores: list = field(default_factory=lambda: [1.0] * MAX_CELULAS)
    n_celulas: int = 0            # ultimas celulas calibradas (informativo)
    data_cal: str = ""
    cal_id: str = ""

    def __post_init__(self):
        # normaliza tamanho para MAX_CELULAS (defensivo ao carregar JSON antigo)
        f = list(self.fatores or [])
        f = (f + [1.0] * MAX_CELULAS)[:MAX_CELULAS]
        self.fatores = [float(x) if x else 1.0 for x in f]

    def aplicar_celulas(self, v_cels) -> list:
        """Aplica o fator de cada celula. Retorna lista de MAX_CELULAS."""
        return [float(v) * self.fatores[i] for i, v in enumerate(v_cels)]

    def gerar_id(self) -> str:
        content = "|".join(f"{f:.6f}" for f in self.fatores) + f"|{self.data_cal}"
        self.cal_id = hashlib.sha1(content.encode()).hexdigest()[:10]
        return self.cal_id

    def tem_correcao(self) -> bool:
        return any(abs(f - 1.0) > 1e-9 for f in self.fatores)

    def qualidade(self) -> str:
        if not self.tem_correcao():
            return "Sem calibracao"
        if any(f < FATOR_MIN_ALERTA or f > FATOR_MAX_ALERTA for f in self.fatores):
            return "Atencao"
        return "OK"


def calcular_fator(v_medida: float, v_referencia: float):
    """fator = V_ref / V_medida. Retorna None se medida invalida (celula
    ausente ou referencia <= 0)."""
    if v_medida < V_MIN_CELULA_CAL or v_referencia <= 0:
        return None
    return float(v_referencia) / float(v_medida)


def fator_fora_faixa(fator: float) -> bool:
    return fator < FATOR_MIN_ALERTA or fator > FATOR_MAX_ALERTA


def carregar_bateria_cal(path) -> BateriaCalibracao:
    if not Path(path).exists():
        return BateriaCalibracao()
    try:
        with open(path) as f:
            d = json.load(f)
        return BateriaCalibracao(**d)
    except Exception:
        return BateriaCalibracao()


def salvar_bateria_cal(path, cal: BateriaCalibracao):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cal.gerar_id()
    with open(path, "w") as f:
        json.dump(asdict(cal), f, indent=2, ensure_ascii=False)
