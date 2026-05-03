"""Leitor serial em thread separada. Formato esperado: raw_e,raw_t,pulsos,dt_us"""
import queue
import threading
import time

import serial


class SerialReader(threading.Thread):
    """Le linhas do firmware e enfileira tuplas (t, raw_e, raw_t, pulsos, dt_us)."""

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
                if len(parts) != 4:
                    continue
                try:
                    raw_e = int(parts[0])
                    raw_t = int(parts[1])
                    pulsos = int(parts[2])
                    dt_us = int(parts[3])
                except ValueError:
                    continue

                t = time.time()
                if not self.queue.full():
                    self.queue.put((t, raw_e, raw_t, pulsos, dt_us))
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
