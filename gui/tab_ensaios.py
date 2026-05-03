"""
Aba de Ensaios: lista os ensaios salvos no banco SQLite,
permite filtrar e comparar dois ensaios lado a lado.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config import ARQUIVO_BANCO
from core import database


class AbaEnsaios(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()
        self.refresh()

    def _build(self):
        # ----- topo: filtros -----
        top = ttk.Frame(self); top.pack(fill="x", padx=5, pady=4)
        ttk.Label(top, text="Helice:").pack(side="left")
        self.var_filt_h = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_filt_h, width=15).pack(side="left", padx=4)
        ttk.Label(top, text="Motor:").pack(side="left", padx=(8, 0))
        self.var_filt_m = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_filt_m, width=15).pack(side="left", padx=4)
        ttk.Button(top, text="🔍 Filtrar", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(top, text="↻ Atualizar", command=self.refresh).pack(side="left")
        ttk.Button(top, text="🗑 Deletar selecionado",
                   command=self._deletar).pack(side="right", padx=4)

        # ----- tabela -----
        cols = ("id", "data", "helice", "motor", "duracao", "emp_max", "rpm_max", "n_pat")
        widths = (40, 140, 200, 200, 70, 80, 80, 50)
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10,
                                 selectmode="extended")
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="x", padx=5, pady=4)

        # ----- comparacao -----
        cmp_frame = ttk.LabelFrame(self, text="Comparacao (selecione 2+ ensaios e clique)")
        cmp_frame.pack(fill="both", expand=True, padx=5, pady=4)

        cmp_top = ttk.Frame(cmp_frame); cmp_top.pack(fill="x", padx=4, pady=4)
        ttk.Button(cmp_top, text="📊 Comparar selecionados",
                   command=self._comparar).pack(side="left", padx=4)
        ttk.Label(cmp_top, text="Eixo Y:").pack(side="left", padx=(10, 2))
        self.var_y = tk.StringVar(value="empuxo_g")
        ttk.Combobox(cmp_top, textvariable=self.var_y, state="readonly",
                     values=["empuxo_g", "torque_Ncm", "p_mec_W",
                             "T_por_P", "C_T", "C_P", "FOM"],
                     width=14).pack(side="left", padx=4)

        self.fig = Figure(figsize=(9, 4), dpi=100, tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=cmp_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def refresh(self):
        if not Path(ARQUIVO_BANCO).exists():
            database.init_db(ARQUIVO_BANCO)

        try:
            ensaios = database.listar_ensaios(
                ARQUIVO_BANCO,
                filtro_helice=self.var_filt_h.get().strip() or None,
                filtro_motor=self.var_filt_m.get().strip() or None,
            )
        except Exception as e:
            messagebox.showerror("Banco", f"Erro: {e}")
            return

        for i in self.tree.get_children():
            self.tree.delete(i)
        for e in ensaios:
            self.tree.insert("", "end", iid=str(e["id"]), values=(
                e["id"],
                e.get("data_iso", "")[:16].replace("T", " "),
                e.get("helice", ""),
                e.get("motor", ""),
                f"{e.get('duracao_s', 0):.1f}s",
                f"{e.get('empuxo_max_g', 0):.0f}g",
                f"{e.get('rpm_max', 0):.0f}",
                e.get("n_patamares", 0),
            ))

    def _deletar(self):
        sel = self.tree.selection()
        if not sel:
            return
        if not messagebox.askyesno("Deletar", f"Deletar {len(sel)} ensaio(s) do banco?\n"
                                              "(o CSV no disco NAO sera apagado)"):
            return
        for iid in sel:
            try:
                database.deletar_ensaio(ARQUIVO_BANCO, int(iid))
            except Exception as e:
                print(f"erro ao deletar {iid}: {e}")
        self.refresh()

    def _comparar(self):
        sel = self.tree.selection()
        if len(sel) < 1:
            messagebox.showwarning("Comparar", "Selecione pelo menos 1 ensaio.")
            return

        self.ax.clear()
        cor_palette = ["#1f6feb", "#d05050", "#0a8a4a", "#c08a00", "#7a40c0", "#40c0a0"]

        coluna_db = {
            "empuxo_g": "empuxo_g",
            "torque_Ncm": "torque_Ncm",
            "p_mec_W": "p_mec_W",
            "T_por_P": "T_por_P",
            "C_T": "C_T", "C_P": "C_P", "FOM": "FOM",
        }[self.var_y.get()]

        for k, iid in enumerate(sel):
            ensaio_id = int(iid)
            pontos = database.get_sweep_pontos(ARQUIVO_BANCO, ensaio_id)
            if not pontos:
                continue
            df = pd.DataFrame(pontos).sort_values("rpm")
            if coluna_db not in df.columns:
                continue
            ensaio_info = self.tree.item(iid, "values")
            label = f"#{ensaio_info[0]} {ensaio_info[2][:20]}"
            self.ax.plot(df["rpm"], df[coluna_db], "o-",
                         color=cor_palette[k % len(cor_palette)],
                         label=label, markersize=6)

        self.ax.set_xlabel("RPM")
        self.ax.set_ylabel(self.var_y.get())
        self.ax.set_title(f"Comparacao - {self.var_y.get()} vs RPM")
        self.ax.grid(True, alpha=0.3)
        if self.ax.has_data():
            self.ax.legend(fontsize=8)
        self.canvas.draw_idle()
