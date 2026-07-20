"""Aba de Calibracao multipontos (celulas + Pitot)."""
import queue
import time
from datetime import datetime

import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from core.calibration import calibrar
from core.pitot import (
    PITOT_OK, PITOT_AUSENTE, MS4525_PA_PER_COUNT_DEFAULT,
    MS4525_RANGE_PA_DEFAULT, calcular_tara, salvar_pitot_cal,
    status_legivel,
)
from core.battery_reader import (
    MAX_CELULAS, BAT_IDADE_MAX_S, FATOR_MIN_ALERTA, FATOR_MAX_ALERTA,
    calcular_fator, fator_fora_faixa, salvar_bateria_cal,
)


# Presets de sensores (range_pa, pa_per_count)
SENSOR_PRESETS = {
    "MS4525DO-DS3BI001DP (+/-1psi, B)": (MS4525_RANGE_PA_DEFAULT,
                                         2.0 * MS4525_RANGE_PA_DEFAULT / (15565.0 - 819.0)),
    "MS4525DO-DS3AI001DP (+/-1psi, A)": (MS4525_RANGE_PA_DEFAULT,
                                         2.0 * MS4525_RANGE_PA_DEFAULT / (14746.0 - 1638.0)),
}


class AbaCalibracao(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.pontos = {"empuxo": [], "torque": []}  # itens: (peso, raw, direcao)
        self._build()

    def _build(self):
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=5, pady=4)

        # Sub-aba 1: Celulas (empuxo/torque) - codigo original
        f_cel = ttk.Frame(nb); nb.add(f_cel, text="Celulas (empuxo/torque)")
        self._build_celulas(f_cel)

        # Sub-aba 2: Pitot
        f_pit = ttk.Frame(nb); nb.add(f_pit, text="Pitot (MS4525DO)")
        self._build_pitot(f_pit)

        # Sub-aba 3: Bateria (fator de correcao por celula)
        f_bat = ttk.Frame(nb); nb.add(f_bat, text="Bateria (celulas)")
        self._build_bateria(f_bat)

    # ============================================================
    # CELULAS (codigo original com 7-tupla na fila)
    # ============================================================
    def _build_celulas(self, parent):
        top = ttk.Frame(parent); top.pack(fill="x", padx=5, pady=4)

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

        body = ttk.Frame(parent); body.pack(fill="both", expand=True, padx=5, pady=4)

        left = ttk.Frame(body); left.pack(side="left", fill="y")
        cols = ("idx", "celula", "direcao", "peso_g", "raw")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=18)
        for c, w in zip(cols, (40, 80, 80, 100, 110)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(side="left", fill="y")
        sb = ttk.Scrollbar(left, command=self.tree.yview); sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        right = ttk.Frame(body); right.pack(side="right", fill="both", expand=True, padx=8)

        self.fig = Figure(figsize=(6, 4), dpi=100, tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.txt_resultado = tk.Text(right, height=12, font=("Courier", 9))
        self.txt_resultado.pack(fill="x", pady=4)

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
                t, re, rt, p, dt, rp, sp = self.app.reader.queue.get(timeout=0.5)
                amos_e.append(re); amos_t.append(rt)
            except queue.Empty:
                break
        if len(amos_e) < 5:
            messagebox.showerror("Tara", "Poucas amostras.")
            return
        self.app.cal.offset_empuxo = float(np.mean(amos_e))
        self.app.cal.offset_torque = float(np.mean(amos_t))
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
                t, re, rt, p, dt, rp, sp = self.app.reader.queue.get(timeout=0.5)
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

    # ============================================================
    # PITOT
    # ============================================================
    def _build_pitot(self, parent):
        top = ttk.Frame(parent); top.pack(fill="x", padx=8, pady=8)

        gb_sensor = ttk.LabelFrame(parent, text="Sensor")
        gb_sensor.pack(fill="x", padx=8, pady=4)

        ttk.Label(gb_sensor, text="Modelo / variante:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.cb_pit_sensor = ttk.Combobox(gb_sensor, width=40, state="readonly",
                                          values=list(SENSOR_PRESETS.keys()) + ["Customizado"])
        self.cb_pit_sensor.set(self.app.pitot_cal.sensor if self.app.pitot_cal.sensor in SENSOR_PRESETS
                                else "Customizado")
        self.cb_pit_sensor.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        self.cb_pit_sensor.bind("<<ComboboxSelected>>", self._on_sensor_select)

        ttk.Label(gb_sensor, text="Range (Pa, +/-):").grid(row=1, column=0, sticky="w", padx=4)
        self.e_pit_range = ttk.Entry(gb_sensor, width=15)
        self.e_pit_range.insert(0, f"{self.app.pitot_cal.range_pa:.2f}")
        self.e_pit_range.grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(gb_sensor, text="Pa por count:").grid(row=2, column=0, sticky="w", padx=4)
        self.e_pit_pa_count = ttk.Entry(gb_sensor, width=15)
        self.e_pit_pa_count.insert(0, f"{self.app.pitot_cal.pa_per_count:.6f}")
        self.e_pit_pa_count.grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(gb_sensor, text="Correcao k (vs anemometro ref):").grid(row=3, column=0, sticky="w", padx=4)
        self.e_pit_k = ttk.Entry(gb_sensor, width=15)
        self.e_pit_k.insert(0, f"{self.app.pitot_cal.k_corr:.6f}")
        self.e_pit_k.grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(gb_sensor, text="(default 1.0)", foreground="grey").grid(row=3, column=2, sticky="w", padx=4)

        gb_tara = ttk.LabelFrame(parent, text="Tara (offset zero)")
        gb_tara.pack(fill="x", padx=8, pady=4)

        ttk.Button(gb_tara, text="Tarar zero (50 amostras com tunel desligado)",
                   command=self._tarar_pitot).grid(row=0, column=0, padx=4, pady=4)

        self.lbl_pit_offset = ttk.Label(gb_tara, text=self._fmt_offset(), font=("Courier", 10))
        self.lbl_pit_offset.grid(row=0, column=1, padx=8)

        gb_acoes = ttk.Frame(parent); gb_acoes.pack(fill="x", padx=8, pady=8)
        ttk.Button(gb_acoes, text="💾 Salvar calibracao do Pitot",
                   command=self._salvar_pitot).pack(side="left", padx=4)

        # Status / leitura ao vivo
        gb_live = ttk.LabelFrame(parent, text="Leitura ao vivo")
        gb_live.pack(fill="x", padx=8, pady=4)
        self.lbl_pit_live = ttk.Label(gb_live, text="(conecte para ler)", font=("Courier", 10))
        self.lbl_pit_live.pack(padx=4, pady=4)
        ttk.Button(gb_live, text="↻ Atualizar leitura",
                   command=self._ler_pitot_live).pack(padx=4, pady=4)

        # info textual
        self.txt_pit_info = tk.Text(parent, height=8, font=("Courier", 9))
        self.txt_pit_info.pack(fill="x", padx=8, pady=4)
        self._refresh_info_pitot()

    def _on_sensor_select(self, *args):
        nome = self.cb_pit_sensor.get()
        if nome in SENSOR_PRESETS:
            range_pa, pa_per_count = SENSOR_PRESETS[nome]
            self.e_pit_range.delete(0, tk.END); self.e_pit_range.insert(0, f"{range_pa:.2f}")
            self.e_pit_pa_count.delete(0, tk.END); self.e_pit_pa_count.insert(0, f"{pa_per_count:.6f}")

    def _fmt_offset(self):
        c = self.app.pitot_cal
        return (f"offset = {c.raw_offset:8.2f}   "
                f"desvio = {c.desvio_tara:5.2f}   "
                f"n = {c.n_amostras_tara:3d}   "
                f"({c.qualidade()})")

    def _tarar_pitot(self):
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
                                 "Nenhuma amostra com status OK. "
                                 "Verifique se o MS4525DO esta conectado em A4/A5.")
            return
        self.app.pitot_cal.raw_offset = offset
        self.app.pitot_cal.n_amostras_tara = n
        self.app.pitot_cal.desvio_tara = desvio
        self.app.pitot_cal.data_offset = datetime.now().isoformat(timespec="seconds")
        self.lbl_pit_offset.config(text=self._fmt_offset())
        self.app.atualizar_status_calibracao()
        messagebox.showinfo("Tara Pitot",
                            f"OK ({n} amostras).\n"
                            f"Offset = {offset:.2f}\n"
                            f"Desvio = {desvio:.2f}")
        self._refresh_info_pitot()

    def _salvar_pitot(self):
        try:
            self.app.pitot_cal.sensor = self.cb_pit_sensor.get()
            self.app.pitot_cal.range_pa = float(self.e_pit_range.get().replace(",", "."))
            self.app.pitot_cal.pa_per_count = float(self.e_pit_pa_count.get().replace(",", "."))
            self.app.pitot_cal.k_corr = float(self.e_pit_k.get().replace(",", "."))
        except ValueError as e:
            messagebox.showerror("Pitot", f"Valor invalido: {e}")
            return
        salvar_pitot_cal(self.app.pitot_cal_path, self.app.pitot_cal)
        self.app.atualizar_status_calibracao()
        self._refresh_info_pitot()
        messagebox.showinfo("Pitot", f"Calibracao salva em\n{self.app.pitot_cal_path}\n\n"
                                     f"cal_id: {self.app.pitot_cal.cal_id}")

    def _refresh_info_pitot(self):
        c = self.app.pitot_cal
        self.txt_pit_info.delete("1.0", "end")
        self.txt_pit_info.insert("end",
            f"sensor       : {c.sensor}\n"
            f"range_pa     : {c.range_pa:.2f}\n"
            f"pa_per_count : {c.pa_per_count:.6f}\n"
            f"raw_offset   : {c.raw_offset:.2f}\n"
            f"k_corr       : {c.k_corr:.6f}\n"
            f"data_offset  : {c.data_offset}\n"
            f"qualidade    : {c.qualidade()}\n"
            f"cal_id       : {c.cal_id or 'NA'}\n"
        )

    def _ler_pitot_live(self):
        if not (self.app.reader and self.app.reader.connected):
            self.lbl_pit_live.config(text="(desconectado)", foreground="grey")
            return
        # le ate 10 amostras e mostra a media
        amos_raw, amos_st = [], []
        t0 = time.time()
        while len(amos_raw) < 10 and time.time() - t0 < 2:
            try:
                t, re, rt, p, dt, rp, sp = self.app.reader.queue.get(timeout=0.3)
                amos_raw.append(rp); amos_st.append(sp)
            except queue.Empty:
                break
        if not amos_raw:
            self.lbl_pit_live.config(text="(sem amostras)", foreground="grey")
            return
        raw_med = float(np.mean(amos_raw))
        st_atual = int(amos_st[-1])
        # converte usando os valores que estao nos campos da UI (sem salvar)
        try:
            offset = self.app.pitot_cal.raw_offset
            pa_per_count = float(self.e_pit_pa_count.get().replace(",", "."))
            k = float(self.e_pit_k.get().replace(",", "."))
        except ValueError:
            pa_per_count = self.app.pitot_cal.pa_per_count
            k = self.app.pitot_cal.k_corr
            offset = self.app.pitot_cal.raw_offset
        q = (raw_med - offset) * pa_per_count * k
        self.lbl_pit_live.config(
            text=f"raw_med = {raw_med:8.1f}   q = {q:+7.2f} Pa   status = {status_legivel(st_atual)}",
            foreground="green" if st_atual == PITOT_OK else "orange",
        )

    # ============================================================
    # BATERIA (fator de correcao por celula)
    # ============================================================
    def _build_bateria(self, parent):
        # estado da calibracao em andamento
        self._bat_medidas = [0.0] * MAX_CELULAS   # ultima leitura ao vivo (raw Arduino)
        self._bat_n_cel = 0
        self._bat_fatores_pendentes = None        # fatores calculados, ainda nao salvos

        ttk.Label(parent, justify="left", foreground="#444", text=(
            "Ajusta a tensao lida de cada celula para um valor de referencia (multimetro).\n"
            "Procedimento: conecte o Arduino da bateria (aba Coleta) com a bateria/fonte ligada,\n"
            "clique 'Ler ao vivo', meça cada celula com multimetro, digite o valor real e\n"
            "'Calcular fatores'. Fator = V_referencia / V_medida, aplicado sobre a leitura."
        )).pack(anchor="w", padx=8, pady=(8, 4))

        gb = ttk.LabelFrame(parent, text="Fatores por celula")
        gb.pack(fill="x", padx=8, pady=4)

        # cabecalho da tabela
        ttk.Label(gb, text="Celula", width=8).grid(row=0, column=0, padx=4, pady=2)
        ttk.Label(gb, text="V medida (ao vivo)", width=18).grid(row=0, column=1, padx=4)
        ttk.Label(gb, text="V referencia", width=14).grid(row=0, column=2, padx=4)
        ttk.Label(gb, text="Fator resultante", width=16).grid(row=0, column=3, padx=4)

        self.bat_var_medida = []
        self.bat_entry_ref = []
        self.bat_var_fator = []
        cal = self.app.bateria_cal
        for i in range(MAX_CELULAS):
            ttk.Label(gb, text=f"Cel {i+1}").grid(row=i + 1, column=0, padx=4, pady=1)

            v_med = tk.StringVar(value="—")
            ttk.Label(gb, textvariable=v_med, font=("Courier", 10),
                      foreground="#7a3aa0").grid(row=i + 1, column=1, padx=4)
            self.bat_var_medida.append(v_med)

            e_ref = ttk.Entry(gb, width=12)
            e_ref.grid(row=i + 1, column=2, padx=4)
            self.bat_entry_ref.append(e_ref)

            v_fat = tk.StringVar(value=f"{cal.fatores[i]:.4f}")
            ttk.Label(gb, textvariable=v_fat, font=("Courier", 10)).grid(
                row=i + 1, column=3, padx=4)
            self.bat_var_fator.append(v_fat)

        botoes = ttk.Frame(parent); botoes.pack(fill="x", padx=8, pady=6)
        ttk.Button(botoes, text="↻ Ler ao vivo",
                   command=self._ler_bateria_live).pack(side="left", padx=4)
        ttk.Button(botoes, text="🧮 Calcular fatores",
                   command=self._calcular_fatores_bateria).pack(side="left", padx=4)
        ttk.Button(botoes, text="💾 Salvar",
                   command=self._salvar_bateria).pack(side="left", padx=4)
        ttk.Button(botoes, text="↺ Resetar (fatores = 1.0)",
                   command=self._resetar_bateria).pack(side="left", padx=4)

        self.lbl_bat_status = ttk.Label(parent, text="", foreground="grey")
        self.lbl_bat_status.pack(anchor="w", padx=8)

        self.txt_bat_info = tk.Text(parent, height=9, font=("Courier", 9))
        self.txt_bat_info.pack(fill="x", padx=8, pady=4)
        self._refresh_info_bateria()

    def _ler_bateria_live(self):
        br = self.app.bat_reader
        if not (br and br.connected):
            messagebox.showwarning("Bateria",
                                   "Conecte o Arduino da bateria na aba Coleta primeiro.")
            return
        snap = br.snapshot()
        if snap is None:
            messagebox.showwarning("Bateria",
                                   "Sem dados ainda. Aguarde alguns segundos apos conectar.")
            return
        v_cels, _v_total, idade = snap
        if idade > BAT_IDADE_MAX_S:
            messagebox.showwarning("Bateria",
                                   f"Leitura antiga ({idade:.0f}s). Verifique a conexao.")
            return

        self._bat_n_cel = br.n_celulas
        self._bat_medidas = list(v_cels)
        for i in range(MAX_CELULAS):
            if i < br.n_celulas:
                self.bat_var_medida[i].set(f"{v_cels[i]:.3f} V")
            else:
                self.bat_var_medida[i].set("—")
        self.lbl_bat_status.config(
            text=f"Leitura ao vivo: {br.n_celulas} celulas (idade {idade:.1f}s). "
                 f"Digite a referencia e calcule.",
            foreground="green")

    def _calcular_fatores_bateria(self):
        if self._bat_n_cel == 0:
            messagebox.showwarning("Bateria", "Clique em 'Ler ao vivo' primeiro.")
            return

        # parte dos fatores atuais; so mexe nas celulas com referencia digitada
        novos = list(self.app.bateria_cal.fatores)
        fora, calculou = [], False
        for i in range(self._bat_n_cel):
            ref_str = self.bat_entry_ref[i].get().strip().replace(",", ".")
            if not ref_str:
                continue  # sem referencia -> mantem o fator existente da celula
            try:
                v_ref = float(ref_str)
            except ValueError:
                messagebox.showerror("Bateria", f"Cel {i+1}: referencia invalida.")
                return
            fator = calcular_fator(self._bat_medidas[i], v_ref)
            if fator is None:
                messagebox.showwarning(
                    "Bateria",
                    f"Cel {i+1}: medida {self._bat_medidas[i]:.2f}V muito baixa "
                    f"(sem celula?) ou referencia <= 0. Ignorada.")
                continue
            novos[i] = fator
            calculou = True
            if fator_fora_faixa(fator):
                fora.append((i + 1, fator))

        if not calculou:
            messagebox.showwarning("Bateria", "Nenhuma referencia valida digitada.")
            return

        self._bat_fatores_pendentes = novos
        for i in range(MAX_CELULAS):
            self.bat_var_fator[i].set(f"{novos[i]:.4f}")

        if fora:
            txt = "\n".join(f"  Cel {c}: fator {f:.3f}" for c, f in fora)
            messagebox.showwarning(
                "Fatores fora do esperado",
                f"Estes fatores ficaram fora de ±20% de 1.0:\n{txt}\n\n"
                "Pode indicar celula/divisor errado ou erro de digitacao.\n"
                "Revise a medicao. Vai pedir confirmacao ao salvar.")
        self.lbl_bat_status.config(
            text="Fatores calculados. Clique 'Salvar' para aplicar.",
            foreground="#5050b0")

    def _salvar_bateria(self):
        fatores = (self._bat_fatores_pendentes
                   if self._bat_fatores_pendentes is not None
                   else list(self.app.bateria_cal.fatores))
        fora = [(i + 1, f) for i, f in enumerate(fatores) if fator_fora_faixa(f)]
        if fora:
            txt = "\n".join(f"  Cel {c}: {f:.3f}" for c, f in fora)
            if not messagebox.askyesno(
                    "Confirmar",
                    f"Fatores fora de ±20% de 1.0:\n{txt}\n\nSalvar mesmo assim?"):
                return

        self.app.bateria_cal.fatores = list(fatores)
        if self._bat_n_cel:
            self.app.bateria_cal.n_celulas = self._bat_n_cel
        self.app.bateria_cal.data_cal = datetime.now().isoformat(timespec="seconds")
        salvar_bateria_cal(self.app.bateria_cal_path, self.app.bateria_cal)
        self._bat_fatores_pendentes = None
        self._refresh_info_bateria()
        messagebox.showinfo(
            "Bateria",
            f"Calibracao salva em\n{self.app.bateria_cal_path}\n\n"
            f"cal_id: {self.app.bateria_cal.cal_id}")

    def _resetar_bateria(self):
        if not messagebox.askyesno("Resetar",
                                   "Voltar todos os fatores para 1.0 (sem correcao)?"):
            return
        self.app.bateria_cal.fatores = [1.0] * MAX_CELULAS
        self.app.bateria_cal.data_cal = datetime.now().isoformat(timespec="seconds")
        salvar_bateria_cal(self.app.bateria_cal_path, self.app.bateria_cal)
        self._bat_fatores_pendentes = None
        for i in range(MAX_CELULAS):
            self.bat_var_fator[i].set("1.0000")
            self.bat_entry_ref[i].delete(0, tk.END)
        self._refresh_info_bateria()

    def _refresh_info_bateria(self):
        c = self.app.bateria_cal
        self.txt_bat_info.delete("1.0", "end")
        self.txt_bat_info.insert("end", "=== CALIBRACAO DA BATERIA ===\n")
        for i in range(MAX_CELULAS):
            self.txt_bat_info.insert("end", f"  fator cel{i+1} : {c.fatores[i]:.4f}\n")
        self.txt_bat_info.insert("end",
            f"n_celulas    : {c.n_celulas}\n"
            f"data_cal     : {c.data_cal or 'NA'}\n"
            f"qualidade    : {c.qualidade()}\n"
            f"cal_id       : {c.cal_id or 'NA'}\n")
