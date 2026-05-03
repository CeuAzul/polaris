"""
Calibracao das celulas de carga.

Modelo linear:  raw = A * peso + B  =>  peso = (raw - B) / A

Cada calibracao gera um ID unico (hash SHA-1 dos pontos + data) que
e referenciado em todos os ensaios feitos com ela. Isso garante
rastreabilidade total: dado um CSV, sabemos exatamente qual
calibracao foi usada e podemos audita-la.
"""
import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

import numpy as np


@dataclass
class CalibrationModel:
    """Modelo linear de uma celula. peso_g = (raw - B) / A"""
    A: float = 1.0
    B: float = 0.0
    R2: float = 0.0
    n_pontos: int = 0
    erro_max_g: float = 0.0
    histerese_max_g: float = 0.0
    pontos_pesos: list = field(default_factory=list)
    pontos_raws: list = field(default_factory=list)
    direcao: list = field(default_factory=list)   # "subida" ou "descida"
    data: str = ""
    cal_id: str = ""

    def aplicar(self, raw):
        if self.A == 0:
            return 0.0
        return (raw - self.B) / self.A

    def gerar_id(self):
        """ID determinístico baseado no conteudo da calibracao."""
        content = (
            f"{self.A:.6f}|{self.B:.6f}|{self.n_pontos}|"
            f"{','.join(f'{p:.4f}' for p in self.pontos_pesos)}|"
            f"{','.join(str(r) for r in self.pontos_raws)}|"
            f"{self.data}"
        )
        h = hashlib.sha1(content.encode()).hexdigest()[:10]
        self.cal_id = h
        return h

    def qualidade(self):
        """Retorna ('OK', 'Atencao', 'Ruim') baseado em R^2 e histerese."""
        if self.n_pontos < 2:
            return "Sem calibracao"
        if self.R2 < 0.99:
            return "Ruim"
        if self.R2 < 0.999 or self.histerese_max_g > 5.0:
            return "Atencao"
        return "OK"


@dataclass
class Calibration:
    """Conjunto de calibracoes do sistema (empuxo + torque + offsets de tara)."""
    empuxo: CalibrationModel = field(default_factory=CalibrationModel)
    torque: CalibrationModel = field(default_factory=CalibrationModel)
    offset_empuxo: float = 0.0    # raw counts subtraidos antes de aplicar
    offset_torque: float = 0.0
    data_offset: str = ""

    def salvar(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # garante ID atualizado
        self.empuxo.gerar_id()
        self.torque.gerar_id()
        with open(path, "w") as f:
            json.dump({
                "empuxo": asdict(self.empuxo),
                "torque": asdict(self.torque),
                "offset_empuxo": self.offset_empuxo,
                "offset_torque": self.offset_torque,
                "data_offset": self.data_offset,
            }, f, indent=2, ensure_ascii=False)

    @classmethod
    def carregar(cls, path):
        if not Path(path).exists():
            return cls()
        with open(path) as f:
            d = json.load(f)
        c = cls()
        c.empuxo = CalibrationModel(**d.get("empuxo", {}))
        c.torque = CalibrationModel(**d.get("torque", {}))
        c.offset_empuxo = d.get("offset_empuxo", 0.0)
        c.offset_torque = d.get("offset_torque", 0.0)
        c.data_offset = d.get("data_offset", "")
        return c

    def cal_id_global(self):
        """Hash combinado das duas celulas (vai pro CSV)."""
        return f"{self.empuxo.cal_id or 'NA'}+{self.torque.cal_id or 'NA'}"


# ============================================================
# REGRESSAO LINEAR + ANALISE
# ============================================================
def regressao_linear(pesos, raws):
    """
    Ajusta raw = A*peso + B por minimos quadrados.
    Retorna (A, B, R2, erro_max_g).
    """
    x = np.asarray(pesos, dtype=float)
    y = np.asarray(raws, dtype=float)
    n = len(x)
    if n < 2:
        return 1.0, 0.0, 0.0, 0.0

    A, B = np.polyfit(x, y, 1)

    y_pred = A * x + B
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    R2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    pesos_pred = (y - B) / A if A != 0 else np.zeros_like(y)
    erro_max = float(np.max(np.abs(pesos_pred - x)))
    return float(A), float(B), float(R2), erro_max


def calcular_histerese(pesos, raws, direcao, A, B):
    """
    Para cada peso que aparece em subida E descida, calcula a diferenca
    em gramas entre os valores previstos pela regressao.
    Retorna (histerese_max_g, dict_detalhes).
    """
    pesos = np.asarray(pesos)
    raws = np.asarray(raws, dtype=float)
    direcao = np.asarray(direcao)

    if A == 0:
        return 0.0, {}

    pesos_pred = (raws - B) / A
    detalhes = {}

    pesos_unicos = np.unique(pesos)
    h_max = 0.0
    for p in pesos_unicos:
        m_sub = (pesos == p) & (direcao == "subida")
        m_des = (pesos == p) & (direcao == "descida")
        if m_sub.any() and m_des.any():
            sub_val = float(np.mean(pesos_pred[m_sub]))
            des_val = float(np.mean(pesos_pred[m_des]))
            diff = des_val - sub_val
            detalhes[float(p)] = {"subida": sub_val, "descida": des_val, "diff": diff}
            if abs(diff) > h_max:
                h_max = abs(diff)
    return float(h_max), detalhes


def calibrar(pesos, raws, direcao, modelo: CalibrationModel):
    """Roda regressao + histerese e atualiza o modelo in-place. Retorna histerese detalhada."""
    A, B, R2, err = regressao_linear(pesos, raws)
    h_max, det = calcular_histerese(pesos, raws, direcao, A, B)

    modelo.A = A
    modelo.B = B
    modelo.R2 = R2
    modelo.n_pontos = len(pesos)
    modelo.erro_max_g = err
    modelo.histerese_max_g = h_max
    modelo.pontos_pesos = list(map(float, pesos))
    modelo.pontos_raws = list(map(float, raws))
    modelo.direcao = list(direcao)
    modelo.data = datetime.now().isoformat(timespec="seconds")
    modelo.gerar_id()
    return det
