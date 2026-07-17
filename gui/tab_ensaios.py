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


# Mapeamento de eixo Y -> coluna na tabela sweep_pontos
COLUNAS_Y_DISPONIVEIS = {
    "empuxo_g": "empuxo_g",
    "torque_Nm": "torque_Nm",
    "p_mec_W": "p_mec_W",
    "T_por_P": "T_por_P",
    "C_T": "C_T",
    "C_P": "C_P",
    "FOM": "FOM",
    "J": "J",
    "eta": "eta",
    "V_med": "V_med",
}

# Mapeamento de eixo X -> coluna
COLUNAS_X_DISPONIVEIS = {
    "RPM": "rpm",
    "J": "J",
    "V_med": "V_med",
}


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
        ttk.Label(top, text="Tipo:").pack(side="left", padx=(8, 0))
        self.var_filt_tipo = tk.StringVar(value="(todos)")
        ttk.Combobox(top, textvariable=self.var_filt_tipo, width=10, state="readonly",
                     values=["(todos)", "estatico", "dinamico"]).pack(side="left", padx=4)
        ttk.Button(top, text="🔍 Filtrar", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(top, text="↻ Atualizar", command=self.refresh).pack(side="left")
        ttk.Button(top, text="🗑 Deletar selecionado",
                   command=self._deletar).pack(side="right", padx=4)

        # ----- tabela -----
        cols = ("id", "data", "tipo", "helice", "motor", "duracao",
                "emp_max", "rpm_max", "V_max", "n_pat")
        widths = (40, 130, 70, 180, 180, 70, 80, 80, 70, 50)
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
        ttk.Label(cmp_top, text="Eixo X:").pack(side="left", padx=(10, 2))
        self.var_x = tk.StringVar(value="RPM")
        ttk.Combobox(cmp_top, textvariable=self.var_x, state="readonly",
                     values=list(COLUNAS_X_DISPONIVEIS.keys()),
                     width=8).pack(side="left", padx=4)
        ttk.Label(cmp_top, text="Eixo Y:").pack(side="left", padx=(10, 2))
        self.var_y = tk.StringVar(value="empuxo_g")
        ttk.Combobox(cmp_top, textvariable=self.var_y, state="readonly",
                     values=list(COLUNAS_Y_DISPONIVEIS.keys()),
                     width=12).pack(side="left", padx=4)

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

        # filtro de tipo (em memoria)
        tipo_sel = self.var_filt_tipo.get()
        if tipo_sel != "(todos)":
            ensaios = [e for e in ensaios
                       if (e.get("tipo_ensaio") or "estatico") == tipo_sel]

        for i in self.tree.get_children():
            self.tree.delete(i)
        for e in ensaios:
            tipo = e.get("tipo_ensaio") or "estatico"
            v_max = e.get("velocidade_max_ms", 0) or 0
            self.tree.insert("", "end", iid=str(e["id"]), values=(
                e["id"],
                e.get("data_iso", "")[:16].replace("T", " "),
                tipo,
                e.get("helice", ""),
                e.get("motor", ""),
                f"{e.get('duracao_s', 0):.1f}s",
                f"{e.get('empuxo_max_g', 0):.0f}g",
                f"{e.get('rpm_max', 0):.0f}",
                f"{v_max:.1f}m/s" if tipo == "dinamico" else "—",
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

        col_y = COLUNAS_Y_DISPONIVEIS[self.var_y.get()]
        col_x = COLUNAS_X_DISPONIVEIS[self.var_x.get()]

        for k, iid in enumerate(sel):
            ensaio_id = int(iid)
            pontos = database.get_sweep_pontos(ARQUIVO_BANCO, ensaio_id)
            if not pontos:
                continue
            df = pd.DataFrame(pontos)
            if col_x not in df.columns or col_y not in df.columns:
                continue
            df = df.sort_values(col_x)
            ensaio_info = self.tree.item(iid, "values")
            label = f"#{ensaio_info[0]} {ensaio_info[3][:20]}"
            self.ax.plot(df[col_x], df[col_y], "o-",
                         color=cor_palette[k % len(cor_palette)],
                         label=label, markersize=6)

        self.ax.set_xlabel(self.var_x.get())
        self.ax.set_ylabel(self.var_y.get())
        self.ax.set_title(f"Comparacao - {self.var_y.get()} vs {self.var_x.get()}")
        self.ax.grid(True, alpha=0.3)
        if self.ax.has_data():
            self.ax.legend(fontsize=8)
        self.canvas.draw_idle()
