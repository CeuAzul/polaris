"""
Aba de Analise: carrega CSV de ensaio, extrai sweep, gera FFT,
compara com UIUC, gera relatorio PDF.

Detecta automaticamente se o ensaio e estatico ou dinamico (presenca
da coluna velocidade_ms no CSV) e ajusta plots e tabelas.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config import UIUC_DIR, RELATORIOS_DIR, BRACO_TORQUE_M
from core.sweep_analyzer import extrair_sweep
from core.fft_analysis import fft_sinal, picos_esperados, encontrar_picos_top
from core.uiuc import (
    buscar_helice, _parse_arquivo_static, comparar_com_ensaio,
    buscar_helice_dinamica, carregar_curva_dinamica, comparar_dinamico_com_ensaio,
)
from core.report import gerar_relatorio_pdf


class AbaAnalise(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.df = None
        self.metadados = None
        self.csv_path = None
        self.df_sweep = None
        self.df_uiuc = None
        self.df_uiuc_compare = None
        self.uiuc_info = None
        self.modo_dinamico = False  # detectado a partir do CSV

        self._build()

    def _build(self):
        # ----- Topo -----
        top = ttk.Frame(self); top.pack(fill="x", padx=5, pady=4)
        ttk.Button(top, text="📂 Carregar CSV", command=self._carregar).pack(side="left", padx=2)
        self.lbl_arquivo = ttk.Label(top, text="(nenhum carregado)", foreground="grey")
        self.lbl_arquivo.pack(side="left", padx=8)
        self.lbl_modo = ttk.Label(top, text="", foreground="#5050b0", font=("TkDefaultFont", 10, "bold"))
        self.lbl_modo.pack(side="left", padx=8)

        ttk.Button(top, text="📋 Gerar Relatorio PDF", command=self._gerar_pdf).pack(side="right", padx=2)

        # ----- Sub-abas -----
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=5, pady=4)

        # Sub-aba 1: Visao Geral (serie temporal)
        f_vis = ttk.Frame(nb); nb.add(f_vis, text="Serie Temporal")
        self.fig_v = Figure(figsize=(10, 6), dpi=100, tight_layout=True)
        self.canvas_v = FigureCanvasTkAgg(self.fig_v, master=f_vis)
        self.canvas_v.get_tk_widget().pack(fill="both", expand=True)

        # Sub-aba 2: Sweep
        f_sw = ttk.Frame(nb); nb.add(f_sw, text="Sweep (patamares)")
        sw_top = ttk.Frame(f_sw); sw_top.pack(fill="x", padx=4, pady=4)

        ttk.Label(sw_top, text="Janela (s):").pack(side="left")
        self.var_jan_sw = tk.DoubleVar(value=2.0)
        ttk.Spinbox(sw_top, from_=0.5, to=10, increment=0.5,
                    textvariable=self.var_jan_sw, width=6).pack(side="left", padx=4)

        ttk.Label(sw_top, text="Lim relativo:").pack(side="left", padx=(8, 0))
        self.var_lim_sw = tk.DoubleVar(value=0.03)
        ttk.Spinbox(sw_top, from_=0.005, to=0.5, increment=0.005,
                    textvariable=self.var_lim_sw, width=6).pack(side="left", padx=4)

        ttk.Label(sw_top, text="Min dur (s):").pack(side="left", padx=(8, 0))
        self.var_dur_sw = tk.DoubleVar(value=1.5)
        ttk.Spinbox(sw_top, from_=0.5, to=10, increment=0.5,
                    textvariable=self.var_dur_sw, width=6).pack(side="left", padx=4)

        ttk.Label(sw_top, text="Sinal-base:").pack(side="left", padx=(8, 0))
        self.var_sinal_sw = tk.StringVar(value="empuxo_g")
        ttk.Combobox(sw_top, textvariable=self.var_sinal_sw,
                     values=["empuxo_g", "rpm"], width=10,
                     state="readonly").pack(side="left", padx=4)

        ttk.Label(sw_top, text="Eixo X dos plots:").pack(side="left", padx=(8, 0))
        self.var_eixo_x = tk.StringVar(value="auto")
        ttk.Combobox(sw_top, textvariable=self.var_eixo_x,
                     values=["auto", "RPM", "J"], width=8,
                     state="readonly").pack(side="left", padx=4)

        ttk.Button(sw_top, text="🔍 Detectar patamares",
                   command=self._extrair_sweep).pack(side="left", padx=8)
        ttk.Button(sw_top, text="💾 Exportar tabela",
                   command=self._exportar_sweep).pack(side="left")

        # tabela: colunas variaveis (estatico vs dinamico)
        self.tree_sw = ttk.Treeview(f_sw, show="headings", height=8)
        self.tree_sw.pack(fill="x", padx=4, pady=4)

        # plot do sweep
        self.fig_sw = Figure(figsize=(10, 5), dpi=100, tight_layout=True)
        self.canvas_sw = FigureCanvasTkAgg(self.fig_sw, master=f_sw)
        self.canvas_sw.get_tk_widget().pack(fill="both", expand=True)

        # Sub-aba 3: FFT
        f_fft = ttk.Frame(nb); nb.add(f_fft, text="FFT / Espectro")
        fft_top = ttk.Frame(f_fft); fft_top.pack(fill="x", padx=4, pady=4)

        ttk.Label(fft_top, text="Trecho t inicial (s):").pack(side="left")
        self.var_t_ini = tk.DoubleVar(value=0.0)
        ttk.Spinbox(fft_top, from_=0, to=600, increment=1,
                    textvariable=self.var_t_ini, width=8).pack(side="left", padx=4)

        ttk.Label(fft_top, text="Duracao (s):").pack(side="left", padx=(8, 0))
        self.var_t_dur = tk.DoubleVar(value=10.0)
        ttk.Spinbox(fft_top, from_=1, to=300, increment=1,
                    textvariable=self.var_t_dur, width=8).pack(side="left", padx=4)

        ttk.Button(fft_top, text="🔬 Calcular FFT",
                   command=self._calcular_fft).pack(side="left", padx=8)

        self.fig_fft = Figure(figsize=(10, 5), dpi=100, tight_layout=True)
        self.canvas_fft = FigureCanvasTkAgg(self.fig_fft, master=f_fft)
        self.canvas_fft.get_tk_widget().pack(fill="both", expand=True)

        self.txt_fft = tk.Text(f_fft, height=6, font=("Courier", 9))
        self.txt_fft.pack(fill="x", padx=4, pady=4)

        # Sub-aba 4: UIUC
        f_uiuc = ttk.Frame(nb); nb.add(f_uiuc, text="UIUC")
        uiuc_top = ttk.Frame(f_uiuc); uiuc_top.pack(fill="x", padx=4, pady=4)
        ttk.Button(uiuc_top, text="🔎 Procurar helice no UIUC",
                   command=self._buscar_uiuc).pack(side="left", padx=4)
        self.lbl_uiuc = ttk.Label(uiuc_top, text="(nada carregado)", foreground="grey")
        self.lbl_uiuc.pack(side="left", padx=8)
        ttk.Label(uiuc_top, text="Tolerancia (in):").pack(side="left")
        self.var_tol = tk.DoubleVar(value=0.5)
        ttk.Spinbox(uiuc_top, from_=0.1, to=3, increment=0.1,
                    textvariable=self.var_tol, width=6).pack(side="left")

        self.fig_u = Figure(figsize=(10, 5), dpi=100, tight_layout=True)
        self.canvas_u = FigureCanvasTkAgg(self.fig_u, master=f_uiuc)
        self.canvas_u.get_tk_widget().pack(fill="both", expand=True)

        # tabela UIUC: colunas variaveis tambem
        self.tree_u = ttk.Treeview(f_uiuc, show="headings", height=6)
        self.tree_u.pack(fill="x", padx=4, pady=4)

    # ====================================================
    # CARREGAR
    # ====================================================
    def _carregar(self):
        path = filedialog.askopenfilename(
            filetypes=[("CSV", "*.csv")],
            initialdir=str(Path("ensaios")) if Path("ensaios").exists() else None,
        )
        if not path:
            return
        try:
            self.df = pd.read_csv(path, comment="#")
        except Exception as e:
            messagebox.showerror("Carregar", f"Erro: {e}")
            return

        self.csv_path = path
        # tenta carregar metadados do JSON paralelo
        json_path = Path(path).with_suffix(".json")
        if json_path.exists():
            try:
                with open(json_path) as f:
                    self.metadados = json.load(f).get("metadados")
            except Exception:
                self.metadados = None
        else:
            self.metadados = None

        # Detecta modo dinamico
        self.modo_dinamico = self._detectar_modo_dinamico()

        self.lbl_arquivo.config(
            text=f"{Path(path).name}  ({len(self.df)} amostras, {self.df['t_s'].iloc[-1]:.1f}s)",
            foreground="black"
        )
        if self.modo_dinamico:
            self.lbl_modo.config(text="MODO DINAMICO (J>0)")
        else:
            self.lbl_modo.config(text="MODO ESTATICO (J=0)")

        self._configurar_tabelas()
        self._plot_serie_temporal()

    def _detectar_modo_dinamico(self) -> bool:
        if self.df is None:
            return False
        if "velocidade_ms" not in self.df.columns:
            return False
        # exige amostras significativas com V > 0.5 m/s para considerar dinamico
        v = self.df["velocidade_ms"].fillna(0).to_numpy()
        return bool(np.any(v > 0.5))

    def _configurar_tabelas(self):
        """Ajusta colunas da tabela de sweep e UIUC conforme modo."""
        if self.modo_dinamico:
            cols_sw = ("idx", "rpm", "V_med", "J", "empuxo_g", "torque_Nm", "p_mec_W",
                       "C_T", "C_P", "FOM", "eta")
            larg_sw = (40, 70, 70, 60, 80, 80, 80, 70, 70, 60, 60)
            cols_u = ("J", "CT_e", "CT_u", "dev_CT", "CP_e", "CP_u", "dev_CP",
                      "eta_e", "eta_u", "dev_eta")
            larg_u = (60, 70, 70, 70, 70, 70, 70, 70, 70, 70)
        else:
            cols_sw = ("idx", "rpm", "rpm_std", "empuxo_g", "torque_Nm", "p_mec_W",
                       "TP", "C_T", "C_P", "FOM")
            larg_sw = (40, 70, 60, 80, 80, 80, 70, 70, 70, 70)
            cols_u = ("rpm", "CT_e", "CT_u", "dev_CT", "CP_e", "CP_u", "dev_CP")
            larg_u = (60, 80, 80, 80, 80, 80, 80)

        self.tree_sw["columns"] = cols_sw
        for c, w in zip(cols_sw, larg_sw):
            self.tree_sw.heading(c, text=c)
            self.tree_sw.column(c, width=w, anchor="center")

        self.tree_u["columns"] = cols_u
        for c, w in zip(cols_u, larg_u):
            self.tree_u.heading(c, text=c)
            self.tree_u.column(c, width=w, anchor="center")

    # ====================================================
    # SERIE TEMPORAL
    # ====================================================
    def _plot_serie_temporal(self):
        if self.df is None:
            return
        n_paineis = 4 if self.modo_dinamico else 3
        self.fig_v.clear()
        ax1 = self.fig_v.add_subplot(n_paineis, 1, 1)
        ax2 = self.fig_v.add_subplot(n_paineis, 1, 2, sharex=ax1)
        ax3 = self.fig_v.add_subplot(n_paineis, 1, 3, sharex=ax1)
        ax4 = self.fig_v.add_subplot(n_paineis, 1, 4, sharex=ax1) if self.modo_dinamico else None

        t = self.df["t_s"].to_numpy()
        ax1.plot(t, self.df["empuxo_g"], "-", color="#1f6feb", linewidth=0.8)
        ax1.set_ylabel("Empuxo (g)"); ax1.grid(True, alpha=0.3)
        ax1.set_title(Path(self.csv_path).name)

        ax2.plot(t, self.df["torque_Nm"], "-", color="#0a8a4a", linewidth=0.8)
        ax2.set_ylabel("Torque (N.m)"); ax2.grid(True, alpha=0.3)

        if "rpm" in self.df.columns:
            ax3.plot(t, self.df["rpm"], "-", color="#c08a00", linewidth=0.8)
            ax3.set_ylabel("RPM")
        ax3.grid(True, alpha=0.3)

        if ax4 is not None and "velocidade_ms" in self.df.columns:
            ax4.plot(t, self.df["velocidade_ms"], "-", color="#5050b0", linewidth=0.8)
            ax4.set_ylabel("V (m/s)")
            ax4.set_xlabel("Tempo (s)"); ax4.grid(True, alpha=0.3)
        else:
            ax3.set_xlabel("Tempo (s)")

        # destaca regioes estaveis se a coluna existir
        if "estavel" in self.df.columns:
            est = self.df["estavel"].astype(bool).to_numpy()
            eixos = [ax1, ax2, ax3]
            if ax4 is not None:
                eixos.append(ax4)
            for ax in eixos:
                ax.fill_between(t, *ax.get_ylim(), where=est,
                                alpha=0.12, color="green",
                                transform=ax.get_xaxis_transform())

        self.canvas_v.draw_idle()

    # ====================================================
    # SWEEP
    # ====================================================
    def _extrair_sweep(self):
        if self.df is None:
            messagebox.showwarning("Sweep", "Carregue um CSV primeiro.")
            return

        # diametro e rho do CSV/metadados
        if "D_m" in self.df.columns and self.df["D_m"].iloc[0] > 0:
            D_m = float(self.df["D_m"].iloc[0])
            D_in = D_m / 0.0254
        elif self.metadados:
            D_in = float(self.metadados["helice"]["diametro_in"])
        else:
            D_in = 16.0

        if "rho" in self.df.columns:
            rho = float(self.df["rho"].iloc[0])
        elif self.metadados:
            rho = float(self.metadados["condicoes"]["rho_kg_m3"])
        else:
            rho = 1.225

        try:
            self.df_sweep = extrair_sweep(
                self.df,
                helice_diametro_in=D_in,
                rho=rho,
                janela_s=self.var_jan_sw.get(),
                limiar_rel=self.var_lim_sw.get(),
                min_dur_s=self.var_dur_sw.get(),
                coluna_estabilidade=self.var_sinal_sw.get(),
            )
        except Exception as e:
            messagebox.showerror("Sweep", f"Erro: {e}")
            return

        # popula tabela conforme modo
        for i in self.tree_sw.get_children():
            self.tree_sw.delete(i)
        if self.modo_dinamico and "J" in self.df_sweep.columns:
            for _, r in self.df_sweep.iterrows():
                self.tree_sw.insert("", "end", values=(
                    int(r["idx"]),
                    f"{r['rpm']:.0f}",
                    f"{r.get('V_med', 0):.2f}",
                    f"{r['J']:.3f}",
                    f"{r['empuxo_g']:.1f}",
                    f"{r['torque_Nm']:.4f}",
                    f"{r['p_mec_W']:.1f}",
                    f"{r['C_T']:.4f}", f"{r['C_P']:.4f}",
                    f"{r['FOM']:.3f}",
                    f"{r['eta']:.3f}",
                ))
        else:
            for _, r in self.df_sweep.iterrows():
                self.tree_sw.insert("", "end", values=(
                    int(r["idx"]),
                    f"{r['rpm']:.0f}", f"{r['rpm_std']:.0f}",
                    f"{r['empuxo_g']:.1f}",
                    f"{r['torque_Nm']:.4f}",
                    f"{r['p_mec_W']:.1f}",
                    f"{r['T_por_P_g_por_W']:.2f}",
                    f"{r['C_T']:.4f}", f"{r['C_P']:.4f}",
                    f"{r['FOM']:.3f}",
                ))

        # plot dos pontos
        self.fig_sw.clear()
        usar_J = (self.var_eixo_x.get() == "J") or (
            self.var_eixo_x.get() == "auto" and self.modo_dinamico
            and "J" in self.df_sweep.columns and not self.df_sweep.empty
        )

        if not self.df_sweep.empty:
            if usar_J and "J" in self.df_sweep.columns:
                sw = self.df_sweep.sort_values("J")
                x = sw["J"]
                xlabel = "J"
                ax_emp = self.fig_sw.add_subplot(221)
                ax_tor = self.fig_sw.add_subplot(222)
                ax_eta = self.fig_sw.add_subplot(223)
                ax_ct = self.fig_sw.add_subplot(224)

                ax_emp.plot(x, sw["C_T"], "o-", color="#1f6feb")
                ax_emp.set_xlabel(xlabel); ax_emp.set_ylabel("C_T"); ax_emp.grid(True, alpha=0.3)

                ax_tor.plot(x, sw["C_P"], "o-", color="#0a8a4a")
                ax_tor.set_xlabel(xlabel); ax_tor.set_ylabel("C_P"); ax_tor.grid(True, alpha=0.3)

                ax_eta.plot(x, sw["eta"], "o-", color="#c0407a")
                ax_eta.set_xlabel(xlabel); ax_eta.set_ylabel("eta"); ax_eta.grid(True, alpha=0.3)
                ax_eta.set_ylim(bottom=0)

                ax_ct.plot(x, sw["empuxo_g"], "o-", color="#7a40c0")
                ax_ct.set_xlabel(xlabel); ax_ct.set_ylabel("Empuxo (g)"); ax_ct.grid(True, alpha=0.3)
            else:
                sw = self.df_sweep.sort_values("rpm")
                x = sw["rpm"]
                xlabel = "RPM"
                ax_emp = self.fig_sw.add_subplot(221)
                ax_tor = self.fig_sw.add_subplot(222)
                ax_eff = self.fig_sw.add_subplot(223)
                ax_fom = self.fig_sw.add_subplot(224)

                ax_emp.plot(x, sw["empuxo_g"], "o-", color="#1f6feb")
                ax_emp.errorbar(x, sw["empuxo_g"], yerr=sw["empuxo_g_std"],
                                fmt="none", color="#1f6feb", alpha=0.5)
                ax_emp.set_xlabel(xlabel); ax_emp.set_ylabel("Empuxo (g)"); ax_emp.grid(True, alpha=0.3)

                ax_tor.plot(x, sw["torque_Nm"], "o-", color="#0a8a4a")
                ax_tor.set_xlabel(xlabel); ax_tor.set_ylabel("Torque (N.m)"); ax_tor.grid(True, alpha=0.3)

                ax_eff.plot(x, sw["T_por_P_g_por_W"], "o-", color="#c0407a")
                ax_eff.set_xlabel(xlabel); ax_eff.set_ylabel("T/P (g/W)"); ax_eff.grid(True, alpha=0.3)

                ax_fom.plot(x, sw["FOM"], "o-", color="#7a40c0")
                ax_fom.set_xlabel(xlabel); ax_fom.set_ylabel("FOM"); ax_fom.grid(True, alpha=0.3)
        else:
            ax = self.fig_sw.add_subplot(111)
            ax.text(0.5, 0.5, "Nenhum patamar detectado", ha="center", va="center",
                    transform=ax.transAxes)

        self.canvas_sw.draw_idle()
        messagebox.showinfo("Sweep", f"{len(self.df_sweep)} patamares detectados.")

    def _exportar_sweep(self):
        if self.df_sweep is None or self.df_sweep.empty:
            messagebox.showwarning("Sweep", "Detecte patamares primeiro.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"{Path(self.csv_path).stem}_sweep.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        self.df_sweep.to_csv(path, index=False)
        messagebox.showinfo("Sweep", f"Salvo: {path}")

    # ====================================================
    # FFT
    # ====================================================
    def _calcular_fft(self):
        if self.df is None:
            messagebox.showwarning("FFT", "Carregue um CSV primeiro.")
            return
        t_ini = self.var_t_ini.get()
        dur = self.var_t_dur.get()
        m = (self.df["t_s"] >= t_ini) & (self.df["t_s"] <= t_ini + dur)
        if m.sum() < 50:
            messagebox.showwarning("FFT", "Trecho muito curto.")
            return

        t = self.df.loc[m, "t_s"].to_numpy()
        emp = self.df.loc[m, "empuxo_g"].to_numpy()
        tor = self.df.loc[m, "torque_Nm"].to_numpy()

        f_e, m_e = fft_sinal(t, emp)
        f_t, m_t = fft_sinal(t, tor)

        rpm_med = float(self.df.loc[m, "rpm"].mean()) if "rpm" in self.df.columns else 0
        n_pas = 2  # default helice 2 pas; para 3 ajustar
        picos_ref = picos_esperados(rpm_med, n_pas=n_pas, n_harmonicas=3)

        self.fig_fft.clear()
        ax1 = self.fig_fft.add_subplot(211)
        ax2 = self.fig_fft.add_subplot(212, sharex=ax1)

        ax1.plot(f_e, m_e, color="#1f6feb")
        ax1.set_ylabel("Empuxo (g)"); ax1.grid(True, alpha=0.3)
        ax1.set_title(f"FFT - trecho [{t_ini:.0f}s, {t_ini+dur:.0f}s], RPM medio = {rpm_med:.0f}")

        ax2.plot(f_t, m_t, color="#0a8a4a")
        ax2.set_ylabel("Torque (N.m)"); ax2.set_xlabel("Frequencia (Hz)")
        ax2.grid(True, alpha=0.3)

        # marca picos esperados
        for nome, fr in picos_ref.items():
            if 0 < fr < (f_e[-1] if len(f_e) else 1000):
                for ax in (ax1, ax2):
                    ax.axvline(fr, color="red", linestyle="--", alpha=0.4, linewidth=0.8)
                ax2.text(fr, ax2.get_ylim()[1] * 0.9, nome, color="red", fontsize=8,
                         rotation=90, va="top")

        ax1.set_xlim(0, max(picos_ref.get("3xBPF", 200) * 1.2, 200))
        self.canvas_fft.draw_idle()

        # picos numericos
        picos_e = encontrar_picos_top(f_e, m_e, n=5)
        self.txt_fft.delete("1.0", "end")
        self.txt_fft.insert("end", "Picos esperados (Hz):\n")
        for nome, fr in picos_ref.items():
            self.txt_fft.insert("end", f"  {nome:8s} = {fr:7.2f} Hz\n")
        self.txt_fft.insert("end", "\nMaiores picos no empuxo:\n")
        for f, m in picos_e:
            self.txt_fft.insert("end", f"  {f:7.2f} Hz  amp = {m:.3f}\n")

    # ====================================================
    # UIUC
    # ====================================================
    def _buscar_uiuc(self):
        if self.df_sweep is None or self.df_sweep.empty:
            messagebox.showwarning("UIUC", "Extraia patamares primeiro (aba Sweep).")
            return

        if self.metadados:
            D_in = float(self.metadados["helice"]["diametro_in"])
            P_in = float(self.metadados["helice"]["passo_in"])
            fab = self.metadados["helice"].get("fabricante", "")
        else:
            messagebox.showwarning("UIUC", "Sem metadados; use o CSV gerado pelo app.")
            return

        if self.modo_dinamico and "J" in self.df_sweep.columns:
            self._uiuc_dinamico(D_in, P_in)
        else:
            self._uiuc_estatico(D_in, P_in, fab)

    def _uiuc_estatico(self, D_in, P_in, fab):
        info = buscar_helice(UIUC_DIR, D_in, P_in, fabricante="APC", tol=self.var_tol.get())
        if not info:
            info = buscar_helice(UIUC_DIR, D_in, P_in, tol=self.var_tol.get())
        if not info:
            self.lbl_uiuc.config(
                text=f"Nenhuma helice {D_in}x{P_in} encontrada em {UIUC_DIR}",
                foreground="orange",
            )
            return

        self.uiuc_info = info
        self.df_uiuc = _parse_arquivo_static(info["arquivo_static"])
        self.df_uiuc_compare = comparar_com_ensaio(self.df_uiuc, self.df_sweep)

        self.lbl_uiuc.config(
            text=f"Carregado (estatico): {info['nome']}",
            foreground="green",
        )

        for i in self.tree_u.get_children():
            self.tree_u.delete(i)
        for _, r in self.df_uiuc_compare.iterrows():
            self.tree_u.insert("", "end", values=(
                f"{r['rpm_ensaio']:.0f}",
                f"{r['CT_ensaio']:.4f}",
                "—" if np.isnan(r["CT_uiuc"]) else f"{r['CT_uiuc']:.4f}",
                "—" if np.isnan(r["CT_dev_pct"]) else f"{r['CT_dev_pct']:+.1f}%",
                f"{r['CP_ensaio']:.4f}",
                "—" if np.isnan(r["CP_uiuc"]) else f"{r['CP_uiuc']:.4f}",
                "—" if np.isnan(r["CP_dev_pct"]) else f"{r['CP_dev_pct']:+.1f}%",
            ))

        self.fig_u.clear()
        ax1 = self.fig_u.add_subplot(121)
        ax2 = self.fig_u.add_subplot(122)

        sw = self.df_sweep.sort_values("rpm")
        u = self.df_uiuc.sort_values("RPM")
        ax1.plot(sw["rpm"], sw["C_T"], "o-", color="#1f6feb", label="Ensaio")
        ax1.plot(u["RPM"], u["CT"], "s--", color="#d05050", label="UIUC")
        ax1.set_xlabel("RPM"); ax1.set_ylabel("C_T")
        ax1.set_title(f"C_T - {info['nome']}"); ax1.legend(); ax1.grid(True, alpha=0.3)

        ax2.plot(sw["rpm"], sw["C_P"], "o-", color="#1f6feb", label="Ensaio")
        ax2.plot(u["RPM"], u["CP"], "s--", color="#d05050", label="UIUC")
        ax2.set_xlabel("RPM"); ax2.set_ylabel("C_P")
        ax2.set_title("C_P"); ax2.legend(); ax2.grid(True, alpha=0.3)

        self.canvas_u.draw_idle()

    def _uiuc_dinamico(self, D_in, P_in):
        # busca helice com arquivos dinamicos
        info = buscar_helice_dinamica(UIUC_DIR, D_in, P_in,
                                      fabricante="APC", tol=self.var_tol.get())
        if not info:
            info = buscar_helice_dinamica(UIUC_DIR, D_in, P_in, tol=self.var_tol.get())
        if not info:
            self.lbl_uiuc.config(
                text=f"Sem dados dinamicos UIUC para {D_in}x{P_in}. "
                     f"Baixe arquivos sem '_static' do site oficial.",
                foreground="orange",
            )
            # fallback: tenta plot estatico mesmo
            return

        # escolhe arquivo cujo RPM nominal e mais proximo da media do ensaio
        rpm_med_ensaio = float(self.df_sweep["rpm"].mean())
        rpm_uiuc, df_uiuc_dyn = carregar_curva_dinamica(info, rpm_med_ensaio)

        self.uiuc_info = info
        self.df_uiuc = df_uiuc_dyn
        self.df_uiuc_compare = comparar_dinamico_com_ensaio(df_uiuc_dyn, self.df_sweep)

        self.lbl_uiuc.config(
            text=f"Carregado (dinamico): {info['nome']} - RPM={rpm_uiuc:.0f} "
                 f"(ensaio medio={rpm_med_ensaio:.0f})",
            foreground="green",
        )

        for i in self.tree_u.get_children():
            self.tree_u.delete(i)
        for _, r in self.df_uiuc_compare.iterrows():
            self.tree_u.insert("", "end", values=(
                f"{r['J_ensaio']:.3f}",
                f"{r['CT_ensaio']:.4f}",
                "—" if np.isnan(r["CT_uiuc"]) else f"{r['CT_uiuc']:.4f}",
                "—" if np.isnan(r["CT_dev_pct"]) else f"{r['CT_dev_pct']:+.1f}%",
                f"{r['CP_ensaio']:.4f}",
                "—" if np.isnan(r["CP_uiuc"]) else f"{r['CP_uiuc']:.4f}",
                "—" if np.isnan(r["CP_dev_pct"]) else f"{r['CP_dev_pct']:+.1f}%",
                f"{r['eta_ensaio']:.3f}",
                "—" if np.isnan(r["eta_uiuc"]) else f"{r['eta_uiuc']:.3f}",
                "—" if np.isnan(r["eta_dev_pct"]) else f"{r['eta_dev_pct']:+.1f}%",
            ))

        self.fig_u.clear()
        ax1 = self.fig_u.add_subplot(131)
        ax2 = self.fig_u.add_subplot(132)
        ax3 = self.fig_u.add_subplot(133)

        sw = self.df_sweep.sort_values("J")
        u = df_uiuc_dyn.sort_values("J")
        ax1.plot(sw["J"], sw["C_T"], "o-", color="#1f6feb", label="Ensaio")
        ax1.plot(u["J"], u["CT"], "s--", color="#d05050", label=f"UIUC @ {rpm_uiuc:.0f}")
        ax1.set_xlabel("J"); ax1.set_ylabel("C_T"); ax1.legend(); ax1.grid(True, alpha=0.3)

        ax2.plot(sw["J"], sw["C_P"], "o-", color="#1f6feb")
        ax2.plot(u["J"], u["CP"], "s--", color="#d05050")
        ax2.set_xlabel("J"); ax2.set_ylabel("C_P"); ax2.grid(True, alpha=0.3)

        ax3.plot(sw["J"], sw["eta"], "o-", color="#1f6feb")
        if "eta" in u.columns:
            ax3.plot(u["J"], u["eta"], "s--", color="#d05050")
        ax3.set_xlabel("J"); ax3.set_ylabel("eta"); ax3.grid(True, alpha=0.3)
        ax3.set_ylim(0, 1.0)

        self.canvas_u.draw_idle()

    # ====================================================
    # PDF
    # ====================================================
    def _gerar_pdf(self):
        if self.df is None:
            messagebox.showwarning("PDF", "Carregue um CSV primeiro.")
            return
        if self.df_sweep is None:
            if messagebox.askyesno("PDF", "Sweep nao foi extraido. Extrair agora?"):
                self._extrair_sweep()
            else:
                return

        nome = f"relatorio_{Path(self.csv_path).stem}.pdf"
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            initialdir=str(RELATORIOS_DIR),
            initialfile=nome,
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return

        cal_info = {
            "cal_id": self.app.cal.cal_id_global(),
            "R2_emp": self.app.cal.empuxo.R2,
            "hist_emp": self.app.cal.empuxo.histerese_max_g,
            "n_emp": self.app.cal.empuxo.n_pontos,
            "R2_tor": self.app.cal.torque.R2,
            "hist_tor": self.app.cal.torque.histerese_max_g,
            "n_tor": self.app.cal.torque.n_pontos,
            "qualidade": f"empuxo={self.app.cal.empuxo.qualidade()}, "
                         f"torque={self.app.cal.torque.qualidade()}",
            "pitot_offset": self.app.pitot_cal.raw_offset,
            "pitot_qualidade": self.app.pitot_cal.qualidade(),
            "pitot_cal_id": self.app.pitot_cal.cal_id,
            "pitot_pa_per_count": self.app.pitot_cal.pa_per_count,
            "pitot_k_corr": self.app.pitot_cal.k_corr,
        }
        observacoes = self.metadados.get("observacoes", "") if self.metadados else ""

        try:
            gerar_relatorio_pdf(
                path,
                metadados=self.metadados or {},
                cal_info=cal_info,
                df_serie=self.df,
                df_sweep=self.df_sweep,
                df_uiuc_compare=self.df_uiuc_compare,
                observacoes=observacoes,
                modo_dinamico=self.modo_dinamico,
            )
        except Exception as e:
            messagebox.showerror("PDF", f"Erro: {e}")
            return
        messagebox.showinfo("PDF", f"Relatorio salvo:\n{path}")
