"""Leitor serial em thread separada.

Suporta dois formatos de protocolo:

  V2 (THRUST_RIG_V2): raw_e,raw_t,pulsos,dt_us
  V3 (THRUST_RIG_V3): raw_e,raw_t,pulsos,dt_us,raw_pitot,status_pitot

A versao e detectada pelo numero de campos. CSVs/coletas antigas
(V2) continuam funcionando: o reader emite raw_pitot=0 e
status_pitot=PITOT_AUSENTE para compatibilidade.
"""
import queue
import threading
import time

import serial

from core.pitot import PITOT_AUSENTE


class SerialReader(threading.Thread):
    """
    Le linhas do firmware e enfileira tuplas:
        (t, raw_e, raw_t, pulsos, dt_us, raw_pitot, status_pitot)

    O ultimo par e sempre presente: para firmware V2, vem como
    (0, PITOT_AUSENTE).
    """

    def __init__(self, port, baudrate=115200):
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.queue = queue.Queue(maxsize=20000)
        self._stop_event = threading.Event()
        self._ser = None
        self.connected = False
        self.last_error = None
        self.firmware_id = None

    def run(self):
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2.0)   # reset do Arduino
            self._ser.reset_input_buffer()
            # pede identificacao
            self._ser.write(b"I")
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
                if line.startswith("ID:"):
                    self.firmware_id = line.split(":", 1)[1]
                    continue
                if line in ("PAUSED", "RESUMED"):
                    continue

                parts = line.split(",")
                # V2: 4 campos. V3: 6 campos. Outros tamanhos sao descartados.
                if len(parts) == 4:
                    try:
                        raw_e = int(parts[0])
                        raw_t = int(parts[1])
                        pulsos = int(parts[2])
                        dt_us = int(parts[3])
                    except ValueError:
                        continue
                    raw_pitot = 0
                    status_pitot = PITOT_AUSENTE
                elif len(parts) == 6:
                    try:
                        raw_e = int(parts[0])
                        raw_t = int(parts[1])
                        pulsos = int(parts[2])
                        dt_us = int(parts[3])
                        raw_pitot = int(parts[4])
                        status_pitot = int(parts[5])
                    except ValueError:
                        continue
                else:
                    continue

                t = time.time()
                if not self.queue.full():
                    self.queue.put((t, raw_e, raw_t, pulsos, dt_us,
                                    raw_pitot, status_pitot))
            except (serial.SerialException, OSError) as e:
                self.last_error = str(e)
                break

        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()

    def send(self, cmd: str):
        if self._ser and self._ser.is_open:
            try:
                self._ser.write(cmd.encode())
            except Exception:
                pass
