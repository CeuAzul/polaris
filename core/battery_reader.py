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
import threading
import time

import serial

# Idade maxima (s) para considerar a leitura da bateria "fresca"
BAT_IDADE_MAX_S = 5.0
MAX_CELULAS = 6


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
