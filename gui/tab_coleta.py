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
    coeficientes, polegadas_para_m,
)
from core.stable_detector import StableDetector
from core.anomaly import AnomalyDetector
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

        self.plot_buffer = deque(maxlen=10000)  # (t, emp_g, tor_g, rpm)
        self._ultimo_alerta_anomalia = ""

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

        self.lbl_anomalia = ttk.Label(ind, text="", foreground="orange", font=("TkDefaultFont", 10, "bold"))
        self.lbl_anomalia.grid(row=2, column=0, columnspan=9, sticky="w", padx=4, pady=(4, 0))

        # ----- Plot -----
        plot_frame = ttk.Frame(self); plot_frame.pack(fill="both", expand=True, padx=5, pady=4)

        self.fig = Figure(figsize=(10, 5), dpi=100, tight_layout=True)
        self.ax_e = self.fig.add_subplot(311)
        self.ax_t = self.fig.add_subplot(312, sharex=self.ax_e)
        self.ax_r = self.fig.add_subplot(313, sharex=self.ax_e)

        self.ax_e.set_ylabel("Empuxo (g)")
        self.ax_t.set_ylabel("Torque (N.m)")
        self.ax_r.set_ylabel("RPM"); self.ax_r.set_xlabel("Tempo (s)")
        for ax in (self.ax_e, self.ax_t, self.ax_r):
            ax.grid(True, alpha=0.3)

        self.line_e, = self.ax_e.plot([], [], color="#1f6feb", linewidth=1)
        self.line_t, = self.ax_t.plot([], [], color="#0a8a4a", linewidth=1)
        self.line_r, = self.ax_r.plot([], [], color="#c08a00", linewidth=1)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

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
        self.lbl_cal.config(
            text=f"Cal: emp R²={emp.R2:.4f} hist={emp.histerese_max_g:.1f}g  |  "
                 f"tor R²={tor.R2:.4f} hist={tor.histerese_max_g:.1f}g",
            foreground=cor,
        )

    # ----------------------------------------------------
    # TARA
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
                t, re, rt, p, dt = self.app.reader.queue.get(timeout=0.5)
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
        for ax in (self.ax_e, self.ax_t, self.ax_r):
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

        with open(path, "w", newline="") as f:
            # cabecalho com metadados
            f.write(f"# Bancada de Empuxo - Ceu Azul\n")
            f.write(f"# data: {self.metadados_atual.get('data','')}\n")
            f.write(f"# operador: {self.metadados_atual.get('operador','')}\n")
            f.write(f"# helice: {self.metadados_atual['helice']}\n")
            f.write(f"# motor: {self.metadados_atual['motor']}\n")
            f.write(f"# bateria: {self.metadados_atual['bateria']}\n")
            f.write(f"# esc: {self.metadados_atual.get('esc','')}\n")
            f.write(f"# condicoes: {self.metadados_atual['condicoes']}\n")
            f.write(f"# cal_id: {cal_id}\n")
            f.write(f"# braco_torque_m: {BRACO_TORQUE_M}\n")
            for t_e, lab in self.eventos_marcados:
                f.write(f"# evento: t={t_e:.3f} {lab}\n")
            f.write("#\n")

            w = csv.writer(f)
            w.writerow([
                "t_s", "raw_e", "raw_t", "pulsos", "dt_us",
                "empuxo_g", "empuxo_N",
                "forca_torque_g", "torque_Nm", "torque_Ncm",
                "rpm",
                "p_mec_W", "T_por_P_g_por_W",
                "C_T", "C_P", "FOM",
                "estavel", "braco_m", "rho", "D_m",
            ])
            for d in self.dados_coleta:
                w.writerow([
                    f"{d['t']:.4f}", d["raw_e"], d["raw_t"], d["pulsos"], d["dt_us"],
                    f"{d['emp_g']:.3f}", f"{d['emp_N']:.4f}",
                    f"{d['tor_g']:.3f}", f"{d['tor_Nm']:.5f}", f"{d['tor_Ncm']:.4f}",
                    f"{d['rpm']:.1f}",
                    f"{d['p_mec_W']:.3f}", f"{d['TP']:.3f}",
                    f"{d['C_T']:.5f}", f"{d['C_P']:.5f}", f"{d['FOM']:.4f}",
                    int(d["estavel"]), BRACO_TORQUE_M, rho, D_m,
                ])

        # Salva metadados em JSON paralelo
        json_path = Path(path).with_suffix(".json")
        import json as _json
        with open(json_path, "w") as f:
            _json.dump({
                "metadados": self.metadados_atual,
                "cal_id": cal_id,
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

        n = 0
        while n < 300:
            try:
                t, raw_e, raw_t, pulsos, dt_us = self.app.reader.queue.get_nowait()
            except queue.Empty:
                break
            n += 1

            emp_g = self.app.cal.empuxo.aplicar(raw_e - self.app.cal.offset_empuxo)
            tor_g = self.app.cal.torque.aplicar(raw_t - self.app.cal.offset_torque)
            rpm = rpm_de_pulsos(pulsos, dt_us, polos)

            emp_N = (emp_g / 1000.0) * GRAVIDADE
            tor_N = (tor_g / 1000.0) * GRAVIDADE
            tor_Nm = tor_N * BRACO_TORQUE_M
            tor_Ncm = tor_Nm * 100.0

            p_mec = potencia_mecanica_W(rpm, tor_g, BRACO_TORQUE_M)
            tp = empuxo_especifico_g_por_W(emp_g, p_mec)
            coefs = coeficientes(emp_g, tor_g, rpm, D_m, rho, BRACO_TORQUE_M)

            estavel, media_g, desv_g = self.detector.update(t, emp_g)

            self.plot_buffer.append((t, emp_g, tor_Nm, rpm))

            # detector de anomalias
            if self.coletando:
                novos = self.anomaly.update(t, emp_g, tor_g, rpm)
                if novos:
                    self._ultimo_alerta_anomalia = novos[-1][1]
                    # marca no plot tambem
                    t_rel = t - self.t_inicio
                    for ax in (self.ax_e, self.ax_t, self.ax_r):
                        ax.axvline(t_rel, color="orange", alpha=0.5, linewidth=0.8)
                    # registra como evento
                    self.eventos_marcados.append((t_rel, f"[anomalia] {novos[-1][1]}"))

            if self.coletando:
                t_rel = t - self.t_inicio
                self.dados_coleta.append({
                    "t": t_rel, "raw_e": raw_e, "raw_t": raw_t,
                    "pulsos": pulsos, "dt_us": dt_us,
                    "emp_g": emp_g, "emp_N": emp_N,
                    "tor_g": tor_g, "tor_Nm": tor_Nm, "tor_Ncm": tor_Ncm,
                    "rpm": rpm, "p_mec_W": p_mec, "TP": tp,
                    "C_T": coefs["C_T"], "C_P": coefs["C_P"], "FOM": coefs["FOM"],
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
                )

        # ---- atualiza indicadores e plot ----
        if self.plot_buffer:
            jan = max(1, int(self.var_filtro.get()))
            ult = list(self.plot_buffer)[-jan:]
            e_filt = float(np.mean([x[1] for x in ult]))     # g
            t_nm_filt = float(np.mean([x[2] for x in ult]))  # N.m (buffer ja em N.m)
            r_filt = float(np.mean([x[3] for x in ult]))     # rpm

            # Converter N.m -> forca_g equivalente no braco da celula.
            # torque_Nm = (forca_g/1000) * g * braco_m
            # logo:   forca_g = torque_Nm / (g * braco_m) * 1000
            torque_Nm = t_nm_filt
            forca_t_g = torque_Nm / (GRAVIDADE * BRACO_TORQUE_M) * 1000.0

            p_mec_f = potencia_mecanica_W(r_filt, forca_t_g, BRACO_TORQUE_M)
            tp_f = empuxo_especifico_g_por_W(e_filt, p_mec_f)
            coefs_f = coeficientes(e_filt, forca_t_g, r_filt, D_m, rho, BRACO_TORQUE_M)

            self.var_emp.set(f"{e_filt:7.1f} g")
            self.var_emp_n.set(f"{(e_filt/1000.0)*GRAVIDADE:6.2f} N")
            self.var_tor.set(f"{t_nm_filt:6.4f} N.m")
            self.var_rpm.set(f"{r_filt:6.0f}")
            self.var_pmec.set(f"{p_mec_f:6.0f} W")
            self.var_tp.set(f"{tp_f:5.2f} g/W")
            self.var_ct.set(f"{coefs_f['C_T']:6.4f}")
            self.var_fom.set(f"{coefs_f['FOM']:5.3f}")

            est, med, des = self.detector.update(self.plot_buffer[-1][0], e_filt)
            if est:
                self.lbl_estavel.config(
                    text=f"REGIME: ESTAVEL  μ={med:.1f}g  σ={des:.1f}g", foreground="green")
            else:
                self.lbl_estavel.config(
                    text=f"REGIME: instavel  σ={des:.1f}g", foreground="orange")

            self.lbl_anomalia.config(
                text=f"⚠ {self._ultimo_alerta_anomalia}" if self._ultimo_alerta_anomalia else ""
            )

            self._desenhar_plot()

    def _resetar_plot(self):
        """Limpa o buffer de plot e reseta os graficos. Nao apaga os dados coletados."""
        self.plot_buffer.clear()
        self.detector.reset()
        self._ultimo_alerta_anomalia = ""

        for ax in (self.ax_e, self.ax_t, self.ax_r):
            ax.cla()

        self.ax_e.set_ylabel("Empuxo (g)")
        self.ax_t.set_ylabel("Torque (N.m)")
        self.ax_r.set_ylabel("RPM")
        self.ax_r.set_xlabel("Tempo (s)")
        for ax in (self.ax_e, self.ax_t, self.ax_r):
            ax.grid(True, alpha=0.3)

        # recria as linhas depois do cla()
        self.line_e, = self.ax_e.plot([], [], color="#1f6feb", linewidth=1)
        self.line_t, = self.ax_t.plot([], [], color="#0a8a4a", linewidth=1)
        self.line_r, = self.ax_r.plot([], [], color="#c08a00", linewidth=1)

        self.lbl_estavel.config(text="REGIME: —", foreground="grey")
        self.lbl_anomalia.config(text="")
        self.canvas.draw_idle()

    def _desenhar_plot(self):
        if not self.plot_buffer:
            return
        arr = np.array(self.plot_buffer)
        t = arr[:, 0] - arr[0, 0]
        emp = arr[:, 1]; tor = arr[:, 2]; rpm = arr[:, 3]

        if t[-1] > PLOT_WINDOW_S:
            mask = t >= (t[-1] - PLOT_WINDOW_S)
            t = t[mask]; emp = emp[mask]; tor = tor[mask]; rpm = rpm[mask]

        jan = max(1, int(self.var_filtro.get()))
        if jan > 1 and len(emp) >= jan:
            k = np.ones(jan) / jan
            emp = np.convolve(emp, k, mode="same")
            tor = np.convolve(tor, k, mode="same")
            rpm = np.convolve(rpm, k, mode="same")

        self.line_e.set_data(t, emp)
        self.line_t.set_data(t, tor)
        self.line_r.set_data(t, rpm)
        for ax in (self.ax_e, self.ax_t, self.ax_r):
            ax.relim(); ax.autoscale_view()
        self.canvas.draw_idle()