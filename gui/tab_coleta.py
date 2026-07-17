"""Aba de Coleta: plot em tempo real, indicadores, controles."""
import csv
import math
import queue
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config import (
    GRAVIDADE, BRACO_TORQUE_M, BRACO_TORQUE_CM,
    PLOT_WINDOW_S, SAMPLE_BUFFER_MAX, ENSAIOS_DIR,
)
from core.derived import (
    rpm_de_pulsos, potencia_mecanica_W, empuxo_especifico_g_por_W,
    coeficientes, polegadas_para_m, LIMIAR_DINAMICO_MS,
)
from core.stable_detector import StableDetector
from core.anomaly import AnomalyDetector
from core.pitot import (
    PITOT_OK, PITOT_AUSENTE, status_legivel, calcular_tara,
    salvar_pitot_cal,
)
from .dialogo_metadados import DialogoMetadados


class AbaColeta(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        self.coletando = False
        self.dados_coleta = []
        self.metadados_atual = None
        self.t_inicio = 0.0
        self.eventos_marcados = []   # (t, label)

        self.detector = StableDetector(janela_s=2.0, limiar_g=20.0)
        self.anomaly = AnomalyDetector()

        # buffer: (t, emp_g, tor_Nm, rpm, V_ms)
        self.plot_buffer = deque(maxlen=10000)
        self._ultimo_alerta_anomalia = ""
        self._pitot_visto = False  # firmware mandou status != AUSENTE alguma vez

        self._build()

    # ----------------------------------------------------
    # LAYOUT
    # ----------------------------------------------------
    def _build(self):
        # ----- Topo: conexao + controles -----
        top = ttk.Frame(self); top.pack(fill="x", padx=5, pady=4)

        ttk.Label(top, text="Porta:").pack(side="left")
        self.cb_porta = ttk.Combobox(top, width=12, values=self.app.listar_portas())
        self.cb_porta.pack(side="left", padx=2)
        ttk.Button(top, text="↻", width=3, command=self._refresh_portas).pack(side="left", padx=2)

        self.btn_conectar = ttk.Button(top, text="Conectar", command=self._toggle_conexao)
        self.btn_conectar.pack(side="left", padx=10)
        self.lbl_status = ttk.Label(top, text="Desconectado", foreground="red")
        self.lbl_status.pack(side="left", padx=5)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Button(top, text="TARA", command=self._tarar).pack(side="left", padx=2)
        ttk.Button(top, text="TARA Pitot", command=self._tarar_pitot).pack(side="left", padx=2)
        self.btn_iniciar = ttk.Button(top, text="▶ Novo Ensaio", command=self._iniciar_coleta)
        self.btn_iniciar.pack(side="left", padx=2)
        self.btn_marcar = ttk.Button(top, text="⚑ Marcar Evento", command=self._marcar_evento, state="disabled")
        self.btn_marcar.pack(side="left", padx=2)
        self.btn_exportar = ttk.Button(top, text="💾 Salvar CSV", command=self._salvar_csv, state="disabled")
        self.btn_exportar.pack(side="left", padx=2)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Button(top, text="🗑 Limpar Gráficos", command=self._resetar_plot).pack(side="left", padx=2)

        # Indicador de calibracao
        self.lbl_cal = ttk.Label(top, text="Cal: —", foreground="grey")
        self.lbl_cal.pack(side="right", padx=8)

        # ----- Filtros e regime estavel -----
        mid = ttk.LabelFrame(self, text="Filtros / Detector de regime estavel")
        mid.pack(fill="x", padx=5, pady=4)

        ttk.Label(mid, text="Media movel (n):").grid(row=0, column=0, sticky="w", padx=5)
        self.var_filtro = tk.IntVar(value=10)
        ttk.Spinbox(mid, from_=1, to=200, textvariable=self.var_filtro, width=6).grid(row=0, column=1, padx=5)

        ttk.Label(mid, text="Janela estavel (s):").grid(row=0, column=2, sticky="w", padx=5)
        self.var_jan = tk.DoubleVar(value=2.0)
        ttk.Spinbox(mid, from_=0.5, to=10, increment=0.5, textvariable=self.var_jan, width=6,
                    command=self._atualizar_detector).grid(row=0, column=3, padx=5)

        ttk.Label(mid, text="Limiar (g):").grid(row=0, column=4, sticky="w", padx=5)
        self.var_lim = tk.DoubleVar(value=20.0)
        ttk.Spinbox(mid, from_=1, to=200, increment=1, textvariable=self.var_lim, width=6,
                    command=self._atualizar_detector).grid(row=0, column=5, padx=5)

        self.lbl_estavel = ttk.Label(mid, text="REGIME: —", font=("TkDefaultFont", 10, "bold"))
        self.lbl_estavel.grid(row=0, column=6, padx=15)

        self.lbl_pitot_status = ttk.Label(mid, text="Pitot: —", foreground="grey")
        self.lbl_pitot_status.grid(row=0, column=7, padx=15)

        # Linha de velocidade manual (visivel apenas no modo manual)
        self.frm_vel_row = ttk.Frame(mid)
        self.frm_vel_row.grid(row=1, column=0, columnspan=8, sticky="w", padx=5, pady=(0, 4))
        ttk.Label(self.frm_vel_row, text="Velocidade do tunel:").pack(side="left", padx=(0, 4))
        self.var_vel_manual = tk.DoubleVar(value=0.0)
        ttk.Spinbox(self.frm_vel_row, from_=0.0, to=30.0, increment=0.5,
                    textvariable=self.var_vel_manual, width=7, format="%.1f").pack(side="left")
        ttk.Label(self.frm_vel_row, text="m/s  — atualize conforme o painel do tunel",
                  foreground="#5050b0").pack(side="left", padx=6)
        self.frm_vel_row.grid_remove()  # oculto ate modo manual ser ativado

        # ----- Indicadores numericos -----
        ind = ttk.LabelFrame(self, text="Leituras")
        ind.pack(fill="x", padx=5, pady=4)
        big = ("TkDefaultFont", 16, "bold")

        self.var_emp = tk.StringVar(value="-- g")
        self.var_emp_n = tk.StringVar(value="-- N")
        self.var_tor = tk.StringVar(value="-- N.m")
        self.var_rpm = tk.StringVar(value="-- rpm")
        self.var_pmec = tk.StringVar(value="-- W")
        self.var_tp = tk.StringVar(value="-- g/W")
        self.var_ct = tk.StringVar(value="-- ")
        self.var_fom = tk.StringVar(value="-- ")
        self.var_v = tk.StringVar(value="-- m/s")
        self.var_q = tk.StringVar(value="-- Pa")
        self.var_j = tk.StringVar(value="-- ")
        self.var_eta = tk.StringVar(value="-- ")

        # linha 1: empuxo, torque, rpm, p_mec
        ttk.Label(ind, text="Empuxo:").grid(row=0, column=0, padx=4, sticky="e")
        ttk.Label(ind, textvariable=self.var_emp, font=big, foreground="#1f6feb").grid(row=0, column=1, sticky="w")
        ttk.Label(ind, textvariable=self.var_emp_n, font=big, foreground="#1f6feb").grid(row=0, column=2, sticky="w", padx=4)

        ttk.Label(ind, text="Torque:").grid(row=0, column=3, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_tor, font=big, foreground="#0a8a4a").grid(row=0, column=4, sticky="w")

        ttk.Label(ind, text="RPM:").grid(row=0, column=5, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_rpm, font=big, foreground="#c08a00").grid(row=0, column=6, sticky="w")

        ttk.Label(ind, text="P_mec:").grid(row=0, column=7, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_pmec, font=big, foreground="#a04040").grid(row=0, column=8, sticky="w")

        # linha 2: T/P, C_T, FOM
        ttk.Label(ind, text="T/P:").grid(row=1, column=0, padx=4, sticky="e")
        ttk.Label(ind, textvariable=self.var_tp, font=("TkDefaultFont", 11)).grid(row=1, column=1, sticky="w")

        ttk.Label(ind, text="C_T:").grid(row=1, column=3, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_ct, font=("TkDefaultFont", 11)).grid(row=1, column=4, sticky="w")

        ttk.Label(ind, text="FOM:").grid(row=1, column=5, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_fom, font=("TkDefaultFont", 11)).grid(row=1, column=6, sticky="w")

        # linha 3: V, q, J, eta (Pitot - so visivel quando habilitado)
        ttk.Label(ind, text="V:").grid(row=2, column=0, padx=4, sticky="e")
        ttk.Label(ind, textvariable=self.var_v, font=("TkDefaultFont", 11), foreground="#5050b0").grid(row=2, column=1, sticky="w")

        ttk.Label(ind, text="q:").grid(row=2, column=3, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_q, font=("TkDefaultFont", 11), foreground="#5050b0").grid(row=2, column=4, sticky="w")

        ttk.Label(ind, text="J:").grid(row=2, column=5, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_j, font=("TkDefaultFont", 11), foreground="#5050b0").grid(row=2, column=6, sticky="w")

        ttk.Label(ind, text="eta:").grid(row=2, column=7, padx=8, sticky="e")
        ttk.Label(ind, textvariable=self.var_eta, font=("TkDefaultFont", 11), foreground="#5050b0").grid(row=2, column=8, sticky="w")

        self.lbl_anomalia = ttk.Label(ind, text="", foreground="orange", font=("TkDefaultFont", 10, "bold"))
        self.lbl_anomalia.grid(row=3, column=0, columnspan=9, sticky="w", padx=4, pady=(4, 0))

        # ----- Plot -----
        plot_frame = ttk.Frame(self); plot_frame.pack(fill="both", expand=True, padx=5, pady=4)

        self.fig = Figure(figsize=(10, 6), dpi=100, tight_layout=True)
        self._criar_eixos()

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _criar_eixos(self):
        """Cria 3 ou 4 eixos conforme Pitot esteja habilitado."""
        usa_pitot = self._pitot_ativo()
        n = 4 if usa_pitot else 3
        self.fig.clear()
        self.ax_e = self.fig.add_subplot(n, 1, 1)
        self.ax_t = self.fig.add_subplot(n, 1, 2, sharex=self.ax_e)
        self.ax_r = self.fig.add_subplot(n, 1, 3, sharex=self.ax_e)
        self.ax_v = self.fig.add_subplot(n, 1, 4, sharex=self.ax_e) if usa_pitot else None

        self.ax_e.set_ylabel("Empuxo (g)")
        self.ax_t.set_ylabel("Torque (N.m)")
        self.ax_r.set_ylabel("RPM")
        if self.ax_v is not None:
            self.ax_v.set_ylabel("V (m/s)")
            self.ax_v.set_xlabel("Tempo (s)")
        else:
            self.ax_r.set_xlabel("Tempo (s)")

        for ax in (self.ax_e, self.ax_t, self.ax_r):
            ax.grid(True, alpha=0.3)
        if self.ax_v is not None:
            self.ax_v.grid(True, alpha=0.3)

        self.line_e, = self.ax_e.plot([], [], color="#1f6feb", linewidth=1)
        self.line_t, = self.ax_t.plot([], [], color="#0a8a4a", linewidth=1)
        self.line_r, = self.ax_r.plot([], [], color="#c08a00", linewidth=1)
        self.line_v = None
        if self.ax_v is not None:
            self.line_v, = self.ax_v.plot([], [], color="#5050b0", linewidth=1)

    def _pitot_ativo(self) -> bool:
        """True se modo dinamico ativo — sensor Pitot OU velocidade manual."""
        if not self.metadados_atual:
            return False
        p = self.metadados_atual.get("pitot", {})
        return bool(p.get("habilitado") or p.get("velocidade_manual"))

    def _modo_manual(self) -> bool:
        """True quando a velocidade e inserida manualmente pelo operador."""
        if not self.metadados_atual:
            return False
        return bool(self.metadados_atual.get("pitot", {}).get("velocidade_manual"))

    def _atualizar_modo_ui(self):
        """Mostra/oculta o spinbox de velocidade manual conforme o modo do ensaio."""
        if self._modo_manual():
            self.frm_vel_row.grid()
        else:
            self.frm_vel_row.grid_remove()

    # ----------------------------------------------------
    # CONEXAO
    # ----------------------------------------------------
    def _refresh_portas(self):
        self.cb_porta["values"] = self.app.listar_portas()

    def _toggle_conexao(self):
        if self.app.reader and self.app.reader.connected:
            self.app.desconectar()
            self.btn_conectar.config(text="Conectar")
            self.lbl_status.config(text="Desconectado", foreground="red")
        else:
            porta = self.cb_porta.get()
            if not porta:
                messagebox.showwarning("Porta", "Selecione uma porta serial.")
                return
            ok, msg = self.app.conectar(porta)
            if ok:
                self.btn_conectar.config(text="Desconectar")
                self.lbl_status.config(text=f"Conectado ({porta})", foreground="green")
            else:
                messagebox.showerror("Conexao", msg)

    def atualizar_status_calibracao(self):
        emp = self.app.cal.empuxo
        tor = self.app.cal.torque
        cor = "green" if emp.qualidade() == "OK" and tor.qualidade() == "OK" else "orange"
        pit = self.app.pitot_cal
        self.lbl_cal.config(
            text=f"Cal: emp R²={emp.R2:.4f} hist={emp.histerese_max_g:.1f}g  |  "
                 f"tor R²={tor.R2:.4f} hist={tor.histerese_max_g:.1f}g  |  "
                 f"pitot offset={pit.raw_offset:.0f} ({pit.qualidade()})",
            foreground=cor,
        )

    # ----------------------------------------------------
    # TARA (celulas)
    # ----------------------------------------------------
    def _tarar(self):
        if not (self.app.reader and self.app.reader.connected):
            messagebox.showwarning("Tara", "Conecte primeiro.")
            return
        if not messagebox.askyesno("Tara", "Confirme: nenhuma carga sobre as celulas e motor parado?"):
            return
        amos_e, amos_t = [], []
        t0 = time.time()
        while len(amos_e) < 30 and time.time() - t0 < 5:
            try:
                t, re, rt, p, dt, rp, sp = self.app.reader.queue.get(timeout=0.5)
                amos_e.append(re); amos_t.append(rt)
            except queue.Empty:
                break
        if len(amos_e) < 5:
            messagebox.showerror("Tara", "Poucas amostras. Verifique a conexao.")
            return
        self.app.cal.offset_empuxo = float(np.mean(amos_e))
        self.app.cal.offset_torque = float(np.mean(amos_t))
        self.app.cal.data_offset = datetime.now().isoformat(timespec="seconds")
        self.app.cal.salvar(self.app.cal_path)
        messagebox.showinfo("Tara", f"Tara feita ({len(amos_e)} amostras).\n"
                                     f"Offset E = {self.app.cal.offset_empuxo:.0f}\n"
                                     f"Offset T = {self.app.cal.offset_torque:.0f}")
        self.atualizar_status_calibracao()

    # ----------------------------------------------------
    # TARA Pitot (zero da pressao dinamica)
    # ----------------------------------------------------
    def _tarar_pitot(self):
        if self._modo_manual():
            messagebox.showinfo("Tara Pitot",
                                "Modo velocidade manual selecionado.\n"
                                "Nao ha sensor Pitot para tarar.\n"
                                "Ajuste a velocidade no spinbox durante o ensaio.")
            return
        if not (self.app.reader and self.app.reader.connected):
            messagebox.showwarning("Tara Pitot", "Conecte primeiro.")
            return
        if not messagebox.askyesno("Tara Pitot",
                                   "Confirme: tunel desligado e helice parada (V=0)?"):
            return
        amos_raw, amos_st = [], []
        t0 = time.time()
        while len(amos_raw) < 50 and time.time() - t0 < 5:
            try:
                t, re, rt, p, dt, rp, sp = self.app.reader.queue.get(timeout=0.5)
                amos_raw.append(rp); amos_st.append(sp)
            except queue.Empty:
                break
        if len(amos_raw) < 5:
            messagebox.showerror("Tara Pitot", "Poucas amostras.")
            return
        offset, desvio, n = calcular_tara(amos_raw, amos_st)
        if n == 0:
            messagebox.showerror("Tara Pitot",
                                 "Nenhuma amostra com status OK.\n"
                                 "Verifique se o MS4525DO esta conectado em A4/A5.")
            return
        self.app.pitot_cal.raw_offset = offset
        self.app.pitot_cal.n_amostras_tara = n
        self.app.pitot_cal.desvio_tara = desvio
        self.app.pitot_cal.data_offset = datetime.now().isoformat(timespec="seconds")
        salvar_pitot_cal(self.app.pitot_cal_path, self.app.pitot_cal)
        messagebox.showinfo("Tara Pitot",
                            f"OK ({n} amostras).\n"
                            f"Offset = {offset:.1f} counts\n"
                            f"Desvio = {desvio:.2f} counts ({self.app.pitot_cal.qualidade()})")
        self.atualizar_status_calibracao()

    # ----------------------------------------------------
    # COLETA
    # ----------------------------------------------------
    def _iniciar_coleta(self):
        if self.coletando:
            self._parar_coleta()
            return

        if not (self.app.reader and self.app.reader.connected):
            messagebox.showwarning("Coleta", "Conecte primeiro.")
            return

        # Avisos sobre calibracao ruim
        if self.app.cal.empuxo.qualidade() in ("Ruim", "Sem calibracao"):
            if not messagebox.askyesno("Calibracao",
                                       "Calibracao da celula de empuxo esta ruim/ausente.\n"
                                       "Deseja prosseguir mesmo assim?"):
                return

        # Pega metadados
        dlg = DialogoMetadados(self, metadados_anteriores=self.metadados_atual)
        if not dlg.resultado:
            return
        self.metadados_atual = dlg.resultado

        # Aviso se modo Pitot sensor sem tara (nao se aplica ao modo manual)
        if self._pitot_ativo() and not self._modo_manual() and self.app.pitot_cal.qualidade() == "Sem tara":
            if not messagebox.askyesno("Pitot",
                                       "O Pitot foi habilitado mas nao tem tara.\n"
                                       "Recomendado: clicar em 'TARA Pitot' antes de iniciar.\n\n"
                                       "Prosseguir mesmo assim?"):
                return

        # Reseta UI/plot para a configuracao atual (com ou sem Pitot)
        self._resetar_plot()
        self._atualizar_modo_ui()

        self.dados_coleta = []
        self.eventos_marcados = []
        self.t_inicio = time.time()
        self.coletando = True
        self.anomaly.reset()
        self.btn_iniciar.config(text="⏹ Parar")
        self.btn_marcar.config(state="normal")
        self.btn_exportar.config(state="disabled")

    def _parar_coleta(self):
        self.coletando = False
        self.btn_iniciar.config(text="▶ Novo Ensaio")
        self.btn_marcar.config(state="disabled")
        self.btn_exportar.config(state="normal" if self.dados_coleta else "disabled")
        if self.dados_coleta:
            messagebox.showinfo("Coleta", f"Coleta encerrada.\n{len(self.dados_coleta)} amostras.\n"
                                          "Clique em 'Salvar CSV' para exportar.")

    def _marcar_evento(self):
        if not self.coletando:
            return
        from tkinter.simpledialog import askstring
        label = askstring("Marcar evento", "Descricao do evento (ex: 'throttle 50%'):", parent=self)
        if not label:
            return
        t_evt = time.time() - self.t_inicio
        self.eventos_marcados.append((t_evt, label))
        # marca no plot
        eixos = [self.ax_e, self.ax_t, self.ax_r]
        if self.ax_v is not None:
            eixos.append(self.ax_v)
        for ax in eixos:
            ax.axvline(t_evt, color="red", alpha=0.4, linewidth=0.8)
        self.canvas.draw_idle()

    def _salvar_csv(self):
        if not self.dados_coleta:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        helice_str = "ens"
        if self.metadados_atual:
            h = self.metadados_atual.get("helice", {})
            helice_str = f"{h.get('fabricante','').replace(' ','_')[:8]}_{int(h.get('diametro_in',0))}x{int(h.get('passo_in',0))}"
        nome = f"ensaio_{helice_str}_{ts}.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialdir=str(ENSAIOS_DIR),
            initialfile=nome,
            filetypes=[("CSV", "*.csv")])
        if not path:
            return

        cal_id = self.app.cal.cal_id_global()
        rho = self.metadados_atual["condicoes"]["rho_kg_m3"] if self.metadados_atual else 1.225
        D_m = polegadas_para_m(self.metadados_atual["helice"]["diametro_in"]) if self.metadados_atual else 0.0
        usa_pitot = self._pitot_ativo()
        tipo_ensaio = self.metadados_atual.get("tipo_ensaio", "estatico") if self.metadados_atual else "estatico"

        with open(path, "w", newline="") as f:
            # cabecalho com metadados
            f.write(f"# Bancada de Empuxo POLARIS - Ceu Azul\n")
            f.write(f"# data: {self.metadados_atual.get('data','')}\n")
            f.write(f"# operador: {self.metadados_atual.get('operador','')}\n")
            f.write(f"# helice: {self.metadados_atual['helice']}\n")
            f.write(f"# motor: {self.metadados_atual['motor']}\n")
            f.write(f"# bateria: {self.metadados_atual['bateria']}\n")
            f.write(f"# esc: {self.metadados_atual.get('esc','')}\n")
            f.write(f"# condicoes: {self.metadados_atual['condicoes']}\n")
            f.write(f"# tipo_ensaio: {tipo_ensaio}\n")
            f.write(f"# pitot: {self.metadados_atual.get('pitot', {})}\n")
            f.write(f"# velocidade_manual: {'sim' if self._modo_manual() else 'nao'}\n")
            f.write(f"# pitot_cal_id: {self.app.pitot_cal.cal_id or 'NA'}\n")
            f.write(f"# pitot_offset: {self.app.pitot_cal.raw_offset:.2f}\n")
            f.write(f"# pitot_pa_per_count: {self.app.pitot_cal.pa_per_count:.6f}\n")
            f.write(f"# pitot_k_corr: {self.app.pitot_cal.k_corr:.6f}\n")
            f.write(f"# cal_id: {cal_id}\n")
            f.write(f"# braco_torque_m: {BRACO_TORQUE_M}\n")
            for t_e, lab in self.eventos_marcados:
                f.write(f"# evento: t={t_e:.3f} {lab}\n")
            f.write("#\n")

            w = csv.writer(f)
            cabecalho = [
                "t_s", "raw_e", "raw_t", "pulsos", "dt_us",
                "raw_pitot", "pitot_status",
                "empuxo_g", "empuxo_N",
                "forca_torque_g", "torque_Nm", "torque_Ncm",
                "rpm",
                "pressao_dinamica_pa", "velocidade_ms",
                "p_mec_W", "T_por_P_g_por_W",
                "C_T", "C_P", "FOM", "J", "eta",
                "estavel", "braco_m", "rho", "D_m",
            ]
            w.writerow(cabecalho)
            for d in self.dados_coleta:
                w.writerow([
                    f"{d['t']:.4f}", d["raw_e"], d["raw_t"], d["pulsos"], d["dt_us"],
                    d.get("raw_pitot", 0), d.get("pitot_status", PITOT_AUSENTE),
                    f"{d['emp_g']:.3f}", f"{d['emp_N']:.4f}",
                    f"{d['tor_g']:.3f}", f"{d['tor_Nm']:.5f}", f"{d['tor_Ncm']:.4f}",
                    f"{d['rpm']:.1f}",
                    f"{d.get('q_pa', 0.0):.3f}", f"{d.get('V_ms', 0.0):.4f}",
                    f"{d['p_mec_W']:.3f}", f"{d['TP']:.3f}",
                    f"{d['C_T']:.5f}", f"{d['C_P']:.5f}", f"{d['FOM']:.4f}",
                    f"{d.get('J', 0.0):.5f}", f"{d.get('eta', 0.0):.4f}",
                    int(d["estavel"]), BRACO_TORQUE_M, rho, D_m,
                ])

        # Salva metadados em JSON paralelo
        json_path = Path(path).with_suffix(".json")
        import json as _json
        with open(json_path, "w") as f:
            _json.dump({
                "metadados": self.metadados_atual,
                "cal_id": cal_id,
                "pitot_cal": {
                    "cal_id": self.app.pitot_cal.cal_id,
                    "sensor": self.app.pitot_cal.sensor,
                    "raw_offset": self.app.pitot_cal.raw_offset,
                    "pa_per_count": self.app.pitot_cal.pa_per_count,
                    "k_corr": self.app.pitot_cal.k_corr,
                },
                "eventos": self.eventos_marcados,
                "n_amostras": len(self.dados_coleta),
                "duracao_s": self.dados_coleta[-1]["t"] if self.dados_coleta else 0,
                "anomalias": self.anomaly.eventos,
            }, f, indent=2, ensure_ascii=False, default=str)

        # Indexa no banco
        try:
            self.app.indexar_no_banco(path, self.metadados_atual, cal_id, self.dados_coleta)
        except Exception as e:
            print(f"[banco] erro: {e}")

        messagebox.showinfo("Salvar", f"CSV: {path}\nJSON: {json_path}")

    # ----------------------------------------------------
    # ATUALIZACAO PERIODICA (chamada do loop principal)
    # ----------------------------------------------------
    def _atualizar_detector(self):
        self.detector = StableDetector(janela_s=self.var_jan.get(),
                                       limiar_g=self.var_lim.get())

    def update_loop(self):
        """Drena a fila do reader e atualiza tudo. Chamado ~a cada 100ms pela App."""
        if not (self.app.reader and self.app.reader.connected):
            return

        D_m = 0.0
        rho = 1.225
        polos = 7
        if self.metadados_atual:
            D_m = polegadas_para_m(self.metadados_atual["helice"]["diametro_in"])
            rho = self.metadados_atual["condicoes"]["rho_kg_m3"]
            polos = self.metadados_atual["motor"]["pares_polos"]
        else:
            # default razoavel quando nao tem ensaio iniciado
            D_m = polegadas_para_m(16.0)
            polos = 7

        usa_pitot_meta = self._pitot_ativo()
        modo_manual = self._modo_manual()
        ultimo_status_pitot = None

        n = 0
        while n < 300:
            try:
                t, raw_e, raw_t, pulsos, dt_us, raw_pitot, status_pitot = \
                    self.app.reader.queue.get_nowait()
            except queue.Empty:
                break
            n += 1

            emp_g = self.app.cal.empuxo.aplicar(raw_e - self.app.cal.offset_empuxo)
            tor_g = self.app.cal.torque.aplicar(raw_t - self.app.cal.offset_torque)
            rpm = rpm_de_pulsos(pulsos, dt_us, polos)

            # Velocidade: manual (operador digita) ou sensor Pitot
            q_pa = 0.0
            V_ms = 0.0
            if modo_manual:
                V_ms = float(self.var_vel_manual.get())
                q_pa = 0.5 * rho * V_ms * V_ms if V_ms > 0 else 0.0
            elif usa_pitot_meta:
                q_pa = self.app.pitot_cal.aplicar_pa(raw_pitot, status_pitot)
                V_ms = self.app.pitot_cal.aplicar_velocidade(raw_pitot, rho, status_pitot)

            if not modo_manual and status_pitot != PITOT_AUSENTE:
                self._pitot_visto = True
            ultimo_status_pitot = status_pitot

            emp_N = (emp_g / 1000.0) * GRAVIDADE
            tor_N = (tor_g / 1000.0) * GRAVIDADE
            tor_Nm = tor_N * BRACO_TORQUE_M
            tor_Ncm = tor_Nm * 100.0

            p_mec = potencia_mecanica_W(rpm, tor_g, BRACO_TORQUE_M)
            tp = empuxo_especifico_g_por_W(emp_g, p_mec)
            coefs = coeficientes(emp_g, tor_g, rpm, D_m, rho, BRACO_TORQUE_M,
                                 V_inflow_ms=V_ms)

            estavel, media_g, desv_g = self.detector.update(t, emp_g)

            self.plot_buffer.append((t, emp_g, tor_Nm, rpm, V_ms))

            # detector de anomalias
            if self.coletando:
                novos = self.anomaly.update(t, emp_g, tor_g, rpm)
                if novos:
                    self._ultimo_alerta_anomalia = novos[-1][1]
                    # marca no plot tambem
                    t_rel = t - self.t_inicio
                    eixos = [self.ax_e, self.ax_t, self.ax_r]
                    if self.ax_v is not None:
                        eixos.append(self.ax_v)
                    for ax in eixos:
                        ax.axvline(t_rel, color="orange", alpha=0.5, linewidth=0.8)
                    self.eventos_marcados.append((t_rel, f"[anomalia] {novos[-1][1]}"))

            if self.coletando:
                t_rel = t - self.t_inicio
                self.dados_coleta.append({
                    "t": t_rel, "raw_e": raw_e, "raw_t": raw_t,
                    "pulsos": pulsos, "dt_us": dt_us,
                    "raw_pitot": raw_pitot, "pitot_status": status_pitot,
                    "emp_g": emp_g, "emp_N": emp_N,
                    "tor_g": tor_g, "tor_Nm": tor_Nm, "tor_Ncm": tor_Ncm,
                    "rpm": rpm,
                    "q_pa": q_pa, "V_ms": V_ms,
                    "p_mec_W": p_mec, "TP": tp,
                    "C_T": coefs["C_T"], "C_P": coefs["C_P"], "FOM": coefs["FOM"],
                    "J": coefs["J"], "eta": coefs["eta"],
                    "estavel": estavel,
                })
                if len(self.dados_coleta) > SAMPLE_BUFFER_MAX:
                    self.dados_coleta = self.dados_coleta[-SAMPLE_BUFFER_MAX:]

            # atualiza servidor remoto
            if self.app.remote_server and self.app.remote_server.httpd:
                self.app.remote_server.atualizar(
                    empuxo_g=emp_g, empuxo_N=emp_N, torque_Nm=tor_Nm,
                    rpm=rpm, p_mec_W=p_mec, T_por_P=tp,
                    estavel=bool(estavel), desvio_g=desv_g,
                    velocidade_ms=V_ms, pressao_dinamica_pa=q_pa,
                    J=coefs["J"], eta=coefs["eta"],
                    pitot_ativo=bool(
                        (modo_manual and V_ms > LIMIAR_DINAMICO_MS) or
                        (usa_pitot_meta and not modo_manual and status_pitot < 3)
                    ),
                )

        # ---- atualiza indicadores e plot ----
        if self.plot_buffer:
            jan = max(1, int(self.var_filtro.get()))
            ult = list(self.plot_buffer)[-jan:]
            e_filt = float(np.mean([x[1] for x in ult]))     # g
            t_nm_filt = float(np.mean([x[2] for x in ult]))  # N.m
            r_filt = float(np.mean([x[3] for x in ult]))     # rpm
            v_filt = float(np.mean([x[4] for x in ult]))     # m/s

            torque_Nm = t_nm_filt
            forca_t_g = torque_Nm / (GRAVIDADE * BRACO_TORQUE_M) * 1000.0

            p_mec_f = potencia_mecanica_W(r_filt, forca_t_g, BRACO_TORQUE_M)
            tp_f = empuxo_especifico_g_por_W(e_filt, p_mec_f)
            coefs_f = coeficientes(e_filt, forca_t_g, r_filt, D_m, rho, BRACO_TORQUE_M,
                                   V_inflow_ms=v_filt)

            self.var_emp.set(f"{e_filt:7.1f} g")
            self.var_emp_n.set(f"{(e_filt/1000.0)*GRAVIDADE:6.2f} N")
            self.var_tor.set(f"{t_nm_filt:6.4f} N.m")
            self.var_rpm.set(f"{r_filt:6.0f}")
            self.var_pmec.set(f"{p_mec_f:6.0f} W")
            self.var_tp.set(f"{tp_f:5.2f} g/W")
            self.var_ct.set(f"{coefs_f['C_T']:6.4f}")
            self.var_fom.set(f"{coefs_f['FOM']:5.3f}")

            if usa_pitot_meta:
                q_filt = 0.5 * rho * v_filt * v_filt if v_filt > 0 else 0.0
                self.var_v.set(f"{v_filt:5.2f} m/s")
                self.var_q.set(f"{q_filt:6.1f} Pa")
                if v_filt > LIMIAR_DINAMICO_MS:
                    self.var_j.set(f"{coefs_f['J']:5.3f}")
                    self.var_eta.set(f"{coefs_f['eta']:5.3f}")
                else:
                    self.var_j.set("0 (estatico)")
                    self.var_eta.set("- (J~0)")
            else:
                self.var_v.set("-- m/s")
                self.var_q.set("-- Pa")
                self.var_j.set("-- ")
                self.var_eta.set("-- ")

            est, med, des = self.detector.update(self.plot_buffer[-1][0], e_filt)
            if est:
                self.lbl_estavel.config(
                    text=f"REGIME: ESTAVEL  μ={med:.1f}g  σ={des:.1f}g", foreground="green")
            else:
                self.lbl_estavel.config(
                    text=f"REGIME: instavel  σ={des:.1f}g", foreground="orange")

            # status do Pitot / velocidade manual
            if modo_manual:
                v_man = float(self.var_vel_manual.get())
                self.lbl_pitot_status.config(
                    text=f"V manual: {v_man:.1f} m/s", foreground="#5050b0")
            elif ultimo_status_pitot is not None:
                if ultimo_status_pitot == PITOT_OK:
                    cor = "green" if usa_pitot_meta else "grey"
                    self.lbl_pitot_status.config(
                        text=f"Pitot: ok ({'ativo' if usa_pitot_meta else 'detectado, desabilitado'})",
                        foreground=cor)
                elif ultimo_status_pitot == PITOT_AUSENTE:
                    self.lbl_pitot_status.config(text="Pitot: ausente", foreground="grey")
                else:
                    self.lbl_pitot_status.config(
                        text=f"Pitot: {status_legivel(ultimo_status_pitot)}",
                        foreground="orange")

            self.lbl_anomalia.config(
                text=f"⚠ {self._ultimo_alerta_anomalia}" if self._ultimo_alerta_anomalia else ""
            )

            self._desenhar_plot()

    def _resetar_plot(self):
        """Limpa o buffer de plot e reseta os graficos. Nao apaga os dados coletados."""
        self.plot_buffer.clear()
        self.detector.reset()
        self._ultimo_alerta_anomalia = ""

        # recria os eixos conforme modo atual (Pitot sensor, manual ou estatico)
        self._criar_eixos()
        self._atualizar_modo_ui()

        self.lbl_estavel.config(text="REGIME: —", foreground="grey")
        self.lbl_anomalia.config(text="")
        self.canvas.draw_idle()

    def _desenhar_plot(self):
        if not self.plot_buffer:
            return
        arr = np.array(self.plot_buffer)
        t = arr[:, 0] - arr[0, 0]
        emp = arr[:, 1]; tor = arr[:, 2]; rpm = arr[:, 3]; V = arr[:, 4]

        if t[-1] > PLOT_WINDOW_S:
            mask = t >= (t[-1] - PLOT_WINDOW_S)
            t = t[mask]; emp = emp[mask]; tor = tor[mask]; rpm = rpm[mask]; V = V[mask]

        jan = max(1, int(self.var_filtro.get()))
        if jan > 1 and len(emp) >= jan:
            k = np.ones(jan) / jan
            emp = np.convolve(emp, k, mode="same")
            tor = np.convolve(tor, k, mode="same")
            rpm = np.convolve(rpm, k, mode="same")
            V = np.convolve(V, k, mode="same")

        self.line_e.set_data(t, emp)
        self.line_t.set_data(t, tor)
        self.line_r.set_data(t, rpm)
        if self.line_v is not None:
            self.line_v.set_data(t, V)

        eixos = [self.ax_e, self.ax_t, self.ax_r]
        if self.ax_v is not None:
            eixos.append(self.ax_v)
        for ax in eixos:
            ax.relim(); ax.autoscale_view()
        self.canvas.draw_idle()
