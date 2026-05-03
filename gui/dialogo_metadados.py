"""Dialogo para coletar metadados do ensaio antes de comecar a coletar."""
import json
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

from core.derived import densidade_ar
from config import ARQUIVO_PERFIS

# Perfis pre-cadastrados (sao salvos no JSON na primeira vez)
PERFIS_DEFAULT = {
    "motores": {
        "SunnySky X4120 KV480": {"modelo": "SunnySky X4120", "kv": 480, "pares_polos": 7},
        "SunnySky X4120 KV550": {"modelo": "SunnySky X4120", "kv": 550, "pares_polos": 7},
        "SunnySky X4120 KV650": {"modelo": "SunnySky X4120", "kv": 650, "pares_polos": 7},
    },
    "helices": {
        "EOLO 16x8":  {"fabricante": "SunnySky/EOLO", "modelo": "EOLO", "diametro_in": 16.0, "passo_in": 8.0},
        "EOLO 15x8":  {"fabricante": "SunnySky/EOLO", "modelo": "EOLO", "diametro_in": 15.0, "passo_in": 8.0},
        "APC 16x8E":  {"fabricante": "APC", "modelo": "Thin Electric", "diametro_in": 16.0, "passo_in": 8.0},
        "APC 15x8E":  {"fabricante": "APC", "modelo": "Thin Electric", "diametro_in": 15.0, "passo_in": 8.0},
    },
}


def carregar_perfis():
    if not Path(ARQUIVO_PERFIS).exists():
        with open(ARQUIVO_PERFIS, "w") as f:
            json.dump(PERFIS_DEFAULT, f, indent=2, ensure_ascii=False)
        return PERFIS_DEFAULT
    try:
        with open(ARQUIVO_PERFIS) as f:
            return json.load(f)
    except Exception:
        return PERFIS_DEFAULT


def salvar_perfis(perfis):
    with open(ARQUIVO_PERFIS, "w") as f:
        json.dump(perfis, f, indent=2, ensure_ascii=False)


class DialogoMetadados(tk.Toplevel):
    """Dialogo modal pedindo metadados do ensaio."""

    def __init__(self, parent, metadados_anteriores=None):
        super().__init__(parent)
        self.title("Novo ensaio - metadados")
        self.transient(parent)
        self.grab_set()
        self.resultado = None

        self.perfis = carregar_perfis()
        ant = metadados_anteriores or {}

        # Notebook com 3 abas
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        # ========== ABA 1: Configuracao ==========
        f1 = ttk.Frame(nb); nb.add(f1, text="Configuracao")

        # Helice
        gb_h = ttk.LabelFrame(f1, text="Helice")
        gb_h.pack(fill="x", padx=8, pady=6)
        ttk.Label(gb_h, text="Perfil:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.cb_helice = ttk.Combobox(gb_h, values=list(self.perfis["helices"].keys()),
                                       width=25, state="readonly")
        self.cb_helice.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        self.cb_helice.bind("<<ComboboxSelected>>", self._on_helice_select)

        ttk.Label(gb_h, text="Fabricante:").grid(row=1, column=0, sticky="w", padx=4)
        self.e_h_fab = ttk.Entry(gb_h, width=25)
        self.e_h_fab.grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(gb_h, text="Modelo:").grid(row=2, column=0, sticky="w", padx=4)
        self.e_h_mod = ttk.Entry(gb_h, width=25)
        self.e_h_mod.grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(gb_h, text="Diametro (in):").grid(row=3, column=0, sticky="w", padx=4)
        self.e_h_diam = ttk.Entry(gb_h, width=10)
        self.e_h_diam.grid(row=3, column=1, sticky="w", padx=4)

        ttk.Label(gb_h, text="Passo (in):").grid(row=4, column=0, sticky="w", padx=4)
        self.e_h_passo = ttk.Entry(gb_h, width=10)
        self.e_h_passo.grid(row=4, column=1, sticky="w", padx=4)

        # Motor
        gb_m = ttk.LabelFrame(f1, text="Motor")
        gb_m.pack(fill="x", padx=8, pady=6)
        ttk.Label(gb_m, text="Perfil:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.cb_motor = ttk.Combobox(gb_m, values=list(self.perfis["motores"].keys()),
                                      width=25, state="readonly")
        self.cb_motor.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        self.cb_motor.bind("<<ComboboxSelected>>", self._on_motor_select)

        ttk.Label(gb_m, text="Modelo:").grid(row=1, column=0, sticky="w", padx=4)
        self.e_m_mod = ttk.Entry(gb_m, width=25)
        self.e_m_mod.grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(gb_m, text="KV:").grid(row=2, column=0, sticky="w", padx=4)
        self.e_m_kv = ttk.Entry(gb_m, width=10)
        self.e_m_kv.grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(gb_m, text="Pares de polos:").grid(row=3, column=0, sticky="w", padx=4)
        self.e_m_polos = ttk.Entry(gb_m, width=10)
        self.e_m_polos.grid(row=3, column=1, sticky="w", padx=4)

        ttk.Label(gb_m, text="(X4120 = 7)", foreground="grey").grid(row=3, column=2, sticky="w", padx=4)

        # ========== ABA 2: Bateria/ESC ==========
        f2 = ttk.Frame(nb); nb.add(f2, text="Bateria / ESC")

        gb_b = ttk.LabelFrame(f2, text="Bateria")
        gb_b.pack(fill="x", padx=8, pady=6)
        ttk.Label(gb_b, text="Cells (S):").grid(row=0, column=0, sticky="w", padx=4)
        self.e_b_s = ttk.Entry(gb_b, width=10); self.e_b_s.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(gb_b, text="Capacidade (mAh):").grid(row=1, column=0, sticky="w", padx=4)
        self.e_b_mah = ttk.Entry(gb_b, width=10); self.e_b_mah.grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(gb_b, text="V inicial (V):").grid(row=2, column=0, sticky="w", padx=4)
        self.e_b_vi = ttk.Entry(gb_b, width=10); self.e_b_vi.grid(row=2, column=1, sticky="w", padx=4)

        gb_e = ttk.LabelFrame(f2, text="ESC")
        gb_e.pack(fill="x", padx=8, pady=6)
        ttk.Label(gb_e, text="Modelo:").grid(row=0, column=0, sticky="w", padx=4)
        self.e_esc = ttk.Entry(gb_e, width=30); self.e_esc.grid(row=0, column=1, sticky="w", padx=4)
        self.e_esc.insert(0, ant.get("esc", "Hobbywing Platinum 120A V4"))

        # ========== ABA 3: Condicoes/Operador ==========
        f3 = ttk.Frame(nb); nb.add(f3, text="Condicoes")

        gb_c = ttk.LabelFrame(f3, text="Condicoes ambientais")
        gb_c.pack(fill="x", padx=8, pady=6)
        ttk.Label(gb_c, text="Temperatura (C):").grid(row=0, column=0, sticky="w", padx=4)
        self.e_T = ttk.Entry(gb_c, width=10); self.e_T.grid(row=0, column=1, sticky="w", padx=4)
        self.e_T.insert(0, str(ant.get("condicoes", {}).get("temp_C", 25.0)))
        ttk.Label(gb_c, text="Pressao (hPa):").grid(row=1, column=0, sticky="w", padx=4)
        self.e_P = ttk.Entry(gb_c, width=10); self.e_P.grid(row=1, column=1, sticky="w", padx=4)
        self.e_P.insert(0, str(ant.get("condicoes", {}).get("pressao_hPa", 1013.0)))
        ttk.Label(gb_c, text="Umidade (%):").grid(row=2, column=0, sticky="w", padx=4)
        self.e_U = ttk.Entry(gb_c, width=10); self.e_U.grid(row=2, column=1, sticky="w", padx=4)
        self.e_U.insert(0, str(ant.get("condicoes", {}).get("umidade_pct", 60.0)))
        ttk.Button(gb_c, text="Calcular rho", command=self._calc_rho).grid(row=3, column=0, padx=4, pady=4)
        self.lbl_rho = ttk.Label(gb_c, text="rho = ? kg/m^3", foreground="blue")
        self.lbl_rho.grid(row=3, column=1, sticky="w", padx=4)

        gb_op = ttk.LabelFrame(f3, text="Operador / Observacoes")
        gb_op.pack(fill="both", expand=True, padx=8, pady=6)
        ttk.Label(gb_op, text="Operador:").grid(row=0, column=0, sticky="w", padx=4)
        self.e_op = ttk.Entry(gb_op, width=30); self.e_op.grid(row=0, column=1, sticky="w", padx=4)
        self.e_op.insert(0, ant.get("operador", ""))
        ttk.Label(gb_op, text="Observacoes:").grid(row=1, column=0, sticky="nw", padx=4)
        self.t_obs = tk.Text(gb_op, width=40, height=5)
        self.t_obs.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        if ant.get("observacoes"):
            self.t_obs.insert("1.0", ant["observacoes"])

        # ========== Botoes ==========
        bf = ttk.Frame(self); bf.pack(fill="x", padx=10, pady=8)
        ttk.Button(bf, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(bf, text="Cancelar", command=self._cancelar).pack(side="right")

        # Pre-selecao a partir do ensaio anterior
        if ant:
            try:
                self._preencher_anterior(ant)
            except Exception:
                pass

        # Valores default
        if not self.cb_helice.get():
            self.cb_helice.set("EOLO 16x8")
            self._on_helice_select()
        if not self.cb_motor.get():
            self.cb_motor.set("SunnySky X4120 KV480")
            self._on_motor_select()
        self._calc_rho()

        self.geometry("+%d+%d" % (parent.winfo_rootx() + 80, parent.winfo_rooty() + 60))
        self.wait_window()

    def _preencher_anterior(self, ant):
        h = ant.get("helice", {})
        self.e_h_fab.delete(0, tk.END); self.e_h_fab.insert(0, h.get("fabricante", ""))
        self.e_h_mod.delete(0, tk.END); self.e_h_mod.insert(0, h.get("modelo", ""))
        self.e_h_diam.delete(0, tk.END); self.e_h_diam.insert(0, str(h.get("diametro_in", 16)))
        self.e_h_passo.delete(0, tk.END); self.e_h_passo.insert(0, str(h.get("passo_in", 8)))
        m = ant.get("motor", {})
        self.e_m_mod.delete(0, tk.END); self.e_m_mod.insert(0, m.get("modelo", ""))
        self.e_m_kv.delete(0, tk.END); self.e_m_kv.insert(0, str(m.get("kv", 480)))
        self.e_m_polos.delete(0, tk.END); self.e_m_polos.insert(0, str(m.get("pares_polos", 7)))
        b = ant.get("bateria", {})
        self.e_b_s.delete(0, tk.END); self.e_b_s.insert(0, str(b.get("cells", 6)))
        self.e_b_mah.delete(0, tk.END); self.e_b_mah.insert(0, str(b.get("mAh", 5000)))

    def _on_helice_select(self, *args):
        nome = self.cb_helice.get()
        h = self.perfis["helices"].get(nome, {})
        self.e_h_fab.delete(0, tk.END); self.e_h_fab.insert(0, h.get("fabricante", ""))
        self.e_h_mod.delete(0, tk.END); self.e_h_mod.insert(0, h.get("modelo", ""))
        self.e_h_diam.delete(0, tk.END); self.e_h_diam.insert(0, str(h.get("diametro_in", "")))
        self.e_h_passo.delete(0, tk.END); self.e_h_passo.insert(0, str(h.get("passo_in", "")))

    def _on_motor_select(self, *args):
        nome = self.cb_motor.get()
        m = self.perfis["motores"].get(nome, {})
        self.e_m_mod.delete(0, tk.END); self.e_m_mod.insert(0, m.get("modelo", ""))
        self.e_m_kv.delete(0, tk.END); self.e_m_kv.insert(0, str(m.get("kv", "")))
        self.e_m_polos.delete(0, tk.END); self.e_m_polos.insert(0, str(m.get("pares_polos", "")))

    def _calc_rho(self):
        try:
            T = float(self.e_T.get().replace(",", "."))
            P = float(self.e_P.get().replace(",", "."))
            U = float(self.e_U.get().replace(",", "."))
            rho = densidade_ar(T, P, U)
            self.lbl_rho.config(text=f"rho = {rho:.4f} kg/m^3")
            self._rho = rho
        except ValueError:
            self.lbl_rho.config(text="rho = (valores invalidos)")
            self._rho = 1.225

    def _ok(self):
        self._calc_rho()
        try:
            md = {
                "helice": {
                    "fabricante": self.e_h_fab.get().strip(),
                    "modelo": self.e_h_mod.get().strip(),
                    "diametro_in": float(self.e_h_diam.get().replace(",", ".")),
                    "passo_in": float(self.e_h_passo.get().replace(",", ".")),
                },
                "motor": {
                    "modelo": self.e_m_mod.get().strip(),
                    "kv": float(self.e_m_kv.get().replace(",", ".")) if self.e_m_kv.get() else 0,
                    "pares_polos": int(float(self.e_m_polos.get().replace(",", "."))),
                },
                "bateria": {
                    "cells": int(self.e_b_s.get()) if self.e_b_s.get() else 0,
                    "mAh": int(self.e_b_mah.get()) if self.e_b_mah.get() else 0,
                    "V_inicial": float(self.e_b_vi.get().replace(",", ".")) if self.e_b_vi.get() else 0,
                },
                "esc": self.e_esc.get().strip(),
                "condicoes": {
                    "temp_C": float(self.e_T.get().replace(",", ".")),
                    "pressao_hPa": float(self.e_P.get().replace(",", ".")),
                    "umidade_pct": float(self.e_U.get().replace(",", ".")),
                    "rho_kg_m3": float(self._rho),
                },
                "operador": self.e_op.get().strip(),
                "observacoes": self.t_obs.get("1.0", "end").strip(),
                "data": datetime.now().isoformat(timespec="seconds"),
            }
        except (ValueError, TypeError) as e:
            messagebox.showerror("Erro", f"Verifique os valores: {e}")
            return

        if md["motor"]["pares_polos"] < 1:
            messagebox.showerror("Erro", "Pares de polos deve ser >= 1")
            return

        self.resultado = md
        self.destroy()

    def _cancelar(self):
        self.resultado = None
        self.destroy()
