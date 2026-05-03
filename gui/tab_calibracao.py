"""Aba de Calibracao multipontos."""
import queue
import time

import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from core.calibration import calibrar


class AbaCalibracao(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.pontos = {"empuxo": [], "torque": []}  # itens: (peso, raw, direcao)
        self._build()

    def _build(self):
        # Topo
        top = ttk.Frame(self); top.pack(fill="x", padx=5, pady=4)

        ttk.Label(top, text="Celula:").pack(side="left")
        self.var_celula = tk.StringVar(value="empuxo")
        ttk.Radiobutton(top, text="Empuxo", variable=self.var_celula, value="empuxo",
                        command=self._refresh_tree).pack(side="left", padx=2)
        ttk.Radiobutton(top, text="Torque", variable=self.var_celula, value="torque",
                        command=self._refresh_tree).pack(side="left", padx=2)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(top, text="Tarar (zero)", command=self._tarar).pack(side="left", padx=4)

        ttk.Label(top, text="Peso (g):").pack(side="left", padx=(10, 2))
        self.entry_peso = ttk.Entry(top, width=10); self.entry_peso.pack(side="left")
        self.entry_peso.bind("<Return>", lambda e: self._add_ponto())

        ttk.Label(top, text="Direcao:").pack(side="left", padx=(8, 2))
        self.var_direcao = tk.StringVar(value="subida")
        ttk.Combobox(top, textvariable=self.var_direcao,
                     values=["subida", "descida"], width=10,
                     state="readonly").pack(side="left")

        ttk.Button(top, text="+ Adicionar Ponto", command=self._add_ponto).pack(side="left", padx=8)
        ttk.Button(top, text="− Remover Ultimo", command=self._remove_ultimo).pack(side="left", padx=2)
        ttk.Button(top, text="× Limpar", command=self._limpar).pack(side="left", padx=2)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(top, text="📊 CALCULAR REGRESSAO", command=self._calcular).pack(side="left", padx=4)
        ttk.Button(top, text="💾 Salvar", command=self._salvar).pack(side="left")

        # Corpo: tabela de pontos a esquerda, plot e resultado a direita
        body = ttk.Frame(self); body.pack(fill="both", expand=True, padx=5, pady=4)

        # Tabela
        left = ttk.Frame(body); left.pack(side="left", fill="y")
        cols = ("idx", "celula", "direcao", "peso_g", "raw")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=18)
        for c, w in zip(cols, (40, 80, 80, 100, 110)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(side="left", fill="y")
        sb = ttk.Scrollbar(left, command=self.tree.yview); sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        # Direita: plot + resultado
        right = ttk.Frame(body); right.pack(side="right", fill="both", expand=True, padx=8)

        self.fig = Figure(figsize=(6, 4), dpi=100, tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.txt_resultado = tk.Text(right, height=12, font=("Courier", 9))
        self.txt_resultado.pack(fill="x", pady=4)

    # ----------------------------------------------------
    def _tarar(self):
        if not (self.app.reader and self.app.reader.connected):
            messagebox.showwarning("Tara", "Conecte primeiro.")
            return
        if not messagebox.askyesno("Tara", "Confirme: nenhum peso na celula?"):
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
            messagebox.showerror("Tara", "Poucas amostras.")
            return
        self.app.cal.offset_empuxo = float(np.mean(amos_e))
        self.app.cal.offset_torque = float(np.mean(amos_t))
        from datetime import datetime
        self.app.cal.data_offset = datetime.now().isoformat(timespec="seconds")
        self.app.cal.salvar(self.app.cal_path)
        messagebox.showinfo("Tara", f"OK ({len(amos_e)} amostras).")

    def _add_ponto(self):
        if not (self.app.reader and self.app.reader.connected):
            messagebox.showwarning("Calibracao", "Conecte primeiro.")
            return
        try:
            peso = float(self.entry_peso.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Calibracao", "Digite um peso numerico.")
            return

        celula = self.var_celula.get()
        direcao = self.var_direcao.get()

        amos = []
        t0 = time.time()
        while len(amos) < 30 and time.time() - t0 < 5:
            try:
                t, re, rt, p, dt = self.app.reader.queue.get(timeout=0.5)
                amos.append(re if celula == "empuxo" else rt)
            except queue.Empty:
                break
        if len(amos) < 5:
            messagebox.showerror("Calibracao", "Poucas amostras.")
            return

        offset = self.app.cal.offset_empuxo if celula == "empuxo" else self.app.cal.offset_torque
        raw_med = float(np.mean(amos)) - offset

        self.pontos[celula].append((peso, raw_med, direcao))
        self.entry_peso.delete(0, tk.END)
        self._refresh_tree()

    def _remove_ultimo(self):
        celula = self.var_celula.get()
        if self.pontos[celula]:
            self.pontos[celula].pop()
            self._refresh_tree()

    def _limpar(self):
        celula = self.var_celula.get()
        if not messagebox.askyesno("Limpar", f"Apagar todos os pontos de {celula}?"):
            return
        self.pontos[celula] = []
        self._refresh_tree()

    def _refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for celula in ("empuxo", "torque"):
            for idx, (p, r, d) in enumerate(self.pontos[celula], start=1):
                if celula == self.var_celula.get():
                    self.tree.insert("", "end",
                                     values=(idx, celula, d, f"{p:.2f}", f"{r:.0f}"))

    def _calcular(self):
        celula = self.var_celula.get()
        pts = self.pontos[celula]
        if len(pts) < 2:
            messagebox.showwarning("Regressao", "Precisa de pelo menos 2 pontos.")
            return

        pesos = [p[0] for p in pts]
        raws = [p[1] for p in pts]
        direcoes = [p[2] for p in pts]

        modelo = self.app.cal.empuxo if celula == "empuxo" else self.app.cal.torque
        det_hist = calibrar(pesos, raws, direcoes, modelo)

        # Plot
        self.ax.clear()
        pesos_arr = np.array(pesos); raws_arr = np.array(raws); dir_arr = np.array(direcoes)
        m_sub = dir_arr == "subida"; m_des = dir_arr == "descida"
        if m_sub.any():
            self.ax.scatter(pesos_arr[m_sub], raws_arr[m_sub], c="#1f6feb",
                            label="subida", s=40, zorder=3)
        if m_des.any():
            self.ax.scatter(pesos_arr[m_des], raws_arr[m_des], c="#d05050",
                            marker="x", label="descida", s=50, zorder=3)
        x_line = np.linspace(min(pesos), max(pesos), 100)
        self.ax.plot(x_line, modelo.A * x_line + modelo.B, "k--", alpha=0.6,
                     label=f"raw = {modelo.A:.2f}·p + {modelo.B:.0f}")
        self.ax.set_xlabel("Peso real (g)"); self.ax.set_ylabel("Leitura bruta (counts)")
        self.ax.set_title(f"Calibracao - {celula}")
        self.ax.legend(); self.ax.grid(True, alpha=0.3)
        self.canvas.draw_idle()

        # Texto
        self.txt_resultado.delete("1.0", "end")
        self.txt_resultado.insert("end",
            f"=== {celula.upper()} ===\n"
            f"N pontos   : {modelo.n_pontos}\n"
            f"A          : {modelo.A:.4f}\n"
            f"B          : {modelo.B:.2f}\n"
            f"R²         : {modelo.R2:.6f}  ({modelo.qualidade()})\n"
            f"Erro max   : {modelo.erro_max_g:.3f} g\n"
            f"Histerese  : {modelo.histerese_max_g:.3f} g\n"
            f"ID         : {modelo.cal_id}\n"
        )
        if det_hist:
            self.txt_resultado.insert("end", "\nHisterese por peso (g):\n")
            for p, info in sorted(det_hist.items()):
                self.txt_resultado.insert(
                    "end",
                    f"  {p:7.1f}: subida={info['subida']:7.2f}  descida={info['descida']:7.2f}  diff={info['diff']:+.3f}\n"
                )

        self.app.atualizar_status_calibracao()

    def _salvar(self):
        self.app.cal.salvar(self.app.cal_path)
        messagebox.showinfo("Salvar", f"Calibracao salva em\n{self.app.cal_path}")
