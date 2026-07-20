"""
Bancada de Empuxo - Ceu Azul Aerodesign
Aplicativo principal V2.

Uso: python app.py
"""
import sys
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

import serial.tools.list_ports

from config import (
    ARQUIVO_CALIBRACAO, ARQUIVO_PITOT_CAL, ARQUIVO_BATERIA_CAL, ARQUIVO_BANCO,
    DEFAULT_BAUDRATE, BAUDRATE_BATERIA, PORTA_REMOTA_PADRAO,
)
from core.calibration import Calibration
from core.pitot import carregar_pitot_cal
from core.serial_reader import SerialReader
from core.battery_reader import BatteryReader, carregar_bateria_cal
from core import database
from core.remote_server import RemoteServer

from gui.tab_coleta import AbaColeta
from gui.tab_calibracao import AbaCalibracao
from gui.tab_analise import AbaAnalise
from gui.tab_ensaios import AbaEnsaios


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Bancada de Empuxo - Ceu Azul Aerodesign  (v2)")
        self.root.geometry("1280x800")

        # Estado
        self.cal_path = ARQUIVO_CALIBRACAO
        self.cal = Calibration.carregar(self.cal_path)
        self.pitot_cal_path = ARQUIVO_PITOT_CAL
        self.pitot_cal = carregar_pitot_cal(self.pitot_cal_path)
        self.bateria_cal_path = ARQUIVO_BATERIA_CAL
        self.bateria_cal = carregar_bateria_cal(self.bateria_cal_path)
        self.reader = None
        self.bat_reader = None
        self.remote_server = None

        # Banco
        if not Path(ARQUIVO_BANCO).exists():
            database.init_db(ARQUIVO_BANCO)

        # ----- Topbar -----
        bar = ttk.Frame(self.root); bar.pack(fill="x", padx=4, pady=2)

        ttk.Label(bar, text="🚁 Bancada V2",
                  font=("TkDefaultFont", 11, "bold")).pack(side="left", padx=4)

        self.var_remoto = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text=f"Monitor remoto (porta {PORTA_REMOTA_PADRAO})",
                        variable=self.var_remoto,
                        command=self._toggle_remoto).pack(side="left", padx=10)
        self.lbl_remoto = ttk.Label(bar, text="", foreground="grey")
        self.lbl_remoto.pack(side="left")

        ttk.Button(bar, text="ℹ Sobre", command=self._sobre).pack(side="right", padx=4)

        # ----- Notebook com abas -----
        nb = ttk.Notebook(self.root); nb.pack(fill="both", expand=True, padx=4, pady=4)

        self.tab_coleta = AbaColeta(nb, self); nb.add(self.tab_coleta, text="📊 Coleta")
        self.tab_cal    = AbaCalibracao(nb, self); nb.add(self.tab_cal, text="⚖ Calibracao")
        self.tab_anal   = AbaAnalise(nb, self); nb.add(self.tab_anal, text="🔬 Analise")
        self.tab_ens    = AbaEnsaios(nb, self); nb.add(self.tab_ens, text="🗂 Ensaios")

        self.tab_coleta.atualizar_status_calibracao()

        # close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # loop principal de update
        self.root.after(100, self._loop)

    # ----------------------------------------------------
    # SERIAL
    # ----------------------------------------------------
    def listar_portas(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def conectar(self, porta):
        if self.reader and self.reader.connected:
            return False, "Ja conectado."
        self.reader = SerialReader(porta, DEFAULT_BAUDRATE)
        self.reader.start()
        # espera o thread tentar abrir a porta
        import time
        for _ in range(40):
            time.sleep(0.1)
            if self.reader.connected:
                return True, "OK"
            if self.reader.last_error:
                err = self.reader.last_error
                self.reader = None
                return False, err
        if self.reader and self.reader.last_error:
            err = self.reader.last_error
            self.reader = None
            return False, err
        return False, "timeout"

    def desconectar(self):
        if self.reader:
            self.reader.stop()
            self.reader.join(timeout=2)
            self.reader = None
        # tambem para coleta se estiver rolando
        if self.tab_coleta.coletando:
            self.tab_coleta._parar_coleta()
        self.tab_coleta.lbl_status.config(text="Desconectado", foreground="red")
        self.tab_coleta.btn_conectar.config(text="Conectar")

    # ----------------------------------------------------
    # SERIAL - Arduino da bateria (segundo Arduino, porta propria)
    # ----------------------------------------------------
    def conectar_bateria(self, porta, n_celulas):
        if self.bat_reader and self.bat_reader.connected:
            return False, "Bateria ja conectada."
        self.bat_reader = BatteryReader(porta, n_celulas, BAUDRATE_BATERIA)
        self.bat_reader.start()
        # espera o thread abrir a porta (inclui ~2.5s do reset do Arduino)
        import time
        for _ in range(60):
            time.sleep(0.1)
            if self.bat_reader.connected:
                return True, "OK"
            if self.bat_reader.last_error:
                err = self.bat_reader.last_error
                self.bat_reader = None
                return False, err
        if self.bat_reader and self.bat_reader.last_error:
            err = self.bat_reader.last_error
            self.bat_reader = None
            return False, err
        return False, "timeout"

    def desconectar_bateria(self):
        if self.bat_reader:
            self.bat_reader.stop()
            self.bat_reader.join(timeout=2)
            self.bat_reader = None

    # ----------------------------------------------------
    # Banco
    # ----------------------------------------------------
    def indexar_no_banco(self, csv_path, metadados, cal_id, dados_coleta):
        """Chamado depois que o usuario salva o CSV. Insere o ensaio no banco."""
        if not dados_coleta:
            return

        emp_max = max((d["emp_g"] for d in dados_coleta), default=0)
        # torque_max em N.m para coerencia com a coluna do banco
        tor_max_nm = max((d["tor_Nm"] for d in dados_coleta), default=0)
        rpm_max = max((d["rpm"] for d in dados_coleta), default=0)
        v_max = max((d.get("V_ms", 0.0) for d in dados_coleta), default=0)
        duracao = dados_coleta[-1]["t"] if dados_coleta else 0

        tipo_ensaio = metadados.get("tipo_ensaio", "estatico")

        sumario = {
            "duracao_s": duracao,
            "empuxo_max_g": emp_max,
            "torque_max_Nm": tor_max_nm,
            "rpm_max": rpm_max,
            "velocidade_max_ms": v_max,
            "tipo_ensaio": tipo_ensaio,
            "pitot_cal_id": self.pitot_cal.cal_id,
            "n_patamares": 0,
            "J_max": 0.0,
            "eta_max": 0.0,
        }

        # tenta extrair sweep ja para indexar os patamares
        try:
            import pandas as pd
            from core.sweep_analyzer import extrair_sweep
            df = pd.read_csv(csv_path, comment="#")
            D_in = float(metadados["helice"]["diametro_in"])
            rho = float(metadados["condicoes"]["rho_kg_m3"])
            df_sw = extrair_sweep(df, helice_diametro_in=D_in, rho=rho)
            sumario["n_patamares"] = len(df_sw)
            if df_sw is not None and not df_sw.empty and "J" in df_sw.columns:
                sumario["J_max"] = float(df_sw["J"].max())
                sumario["eta_max"] = float(df_sw["eta"].max())
        except Exception:
            df_sw = None

        ensaio_id = database.inserir_ensaio(
            ARQUIVO_BANCO, csv_path, metadados, cal_id, sumario,
        )
        if df_sw is not None and not df_sw.empty:
            database.inserir_sweep_pontos(ARQUIVO_BANCO, ensaio_id, df_sw)
        # atualiza a aba de ensaios
        self.tab_ens.refresh()

    # ----------------------------------------------------
    # Status calibracao (chamado pela aba de calibracao)
    # ----------------------------------------------------
    def atualizar_status_calibracao(self):
        self.tab_coleta.atualizar_status_calibracao()

    # ----------------------------------------------------
    # Monitor remoto
    # ----------------------------------------------------
    def _toggle_remoto(self):
        if self.var_remoto.get():
            try:
                self.remote_server = RemoteServer(port=PORTA_REMOTA_PADRAO)
                self.remote_server.start()
                ip = self._meu_ip()
                self.lbl_remoto.config(
                    text=f"http://{ip}:{PORTA_REMOTA_PADRAO}/",
                    foreground="green",
                )
            except Exception as e:
                messagebox.showerror("Monitor remoto", f"Erro: {e}")
                self.var_remoto.set(False)
        else:
            if self.remote_server:
                self.remote_server.stop()
                self.remote_server = None
            self.lbl_remoto.config(text="", foreground="grey")

    def _meu_ip(self):
        """Tenta descobrir o IP local (rede em uso)."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ----------------------------------------------------
    # Loop principal
    # ----------------------------------------------------
    def _loop(self):
        try:
            self.tab_coleta.update_loop()
        except Exception as e:
            print(f"[loop] {e}")
        self.root.after(100, self._loop)

    # ----------------------------------------------------
    # Sobre / fechamento
    # ----------------------------------------------------
    def _sobre(self):
        messagebox.showinfo("Sobre",
            "POLARIS - Bancada de Empuxo - Ceu Azul Aerodesign\n"
            "Versao 3.0 (suporte a Pitot MS4525DO)\n\n"
            "Funcoes:\n"
            "  • Coleta com RPM via fio do ESC\n"
            "  • Pitot opcional (MS4525DO) para empuxo dinamico\n"
            "  • Calibracao multipontos com histerese\n"
            "  • Sweep manual (extracao de patamares)\n"
            "  • Coeficientes adimensionais (C_T, C_P, FOM, J, eta)\n"
            "  • Comparacao com banco UIUC (estatico e dinamico)\n"
            "  • Analise FFT\n"
            "  • Banco SQLite de ensaios\n"
            "  • Monitor remoto via celular\n"
            "  • Relatorio PDF\n")

    def _on_close(self):
        try:
            if self.tab_coleta.coletando and self.tab_coleta.dados_coleta:
                if not messagebox.askyesno("Sair",
                    "Coleta em andamento com dados nao salvos. Sair mesmo assim?"):
                    return
            if self.reader:
                self.reader.stop()
            if self.bat_reader:
                self.bat_reader.stop()
            if self.remote_server:
                self.remote_server.stop()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    # estilo
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
