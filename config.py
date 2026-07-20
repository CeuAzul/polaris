"""Configuracoes globais."""
import os
import sys
from pathlib import Path

# Constantes fisicas
GRAVIDADE = 9.80665                  # m/s^2
RHO_AR_PADRAO = 1.225                # kg/m^3 (ISA, nivel do mar, 15C)

# Geometria da bancada
BRACO_TORQUE_CM = 7.0
BRACO_TORQUE_M = BRACO_TORQUE_CM / 100.0

# Serial
DEFAULT_BAUDRATE = 115200
BAUDRATE_BATERIA = 9600            # Arduino do monitor de bateria (bancada_bateria_v4)
ID_FIRMWARE_V2 = "THRUST_RIG_V2"   # legado (sem Pitot)
ID_FIRMWARE_V3 = "THRUST_RIG_V3"   # atual (com Pitot)
ID_FIRMWARE = ID_FIRMWARE_V3

# Caminhos
ROOT = Path(__file__).parent


def _data_root() -> Path:
    """Onde ficam os DADOS do usuario (config, ensaios, relatorios).

    No modo empacotado/instalado, os dados sao separados do CODIGO
    (que e substituido a cada auto-update) para nunca perder ensaios
    ou calibracao. No modo dev (rodando do repo), mantem tudo no repo,
    preservando o fluxo de trabalho atual da equipe.

    Pode ser forcado por POLARIS_DATA_DIR.
    """
    env = os.environ.get("POLARIS_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "POLARIS"
    return ROOT


DATA_ROOT = _data_root()
# Dados do usuario (persistem entre atualizacoes)
CONFIG_DIR = DATA_ROOT / "config_local"
ENSAIOS_DIR = DATA_ROOT / "ensaios"
RELATORIOS_DIR = DATA_ROOT / "relatorios"
# Referencia que acompanha o codigo (read-only, atualizada junto no update)
UIUC_DIR = ROOT / "uiuc_data"

for _d in (CONFIG_DIR, ENSAIOS_DIR, RELATORIOS_DIR, UIUC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Arquivos de configuracao
ARQUIVO_CALIBRACAO = CONFIG_DIR / "calibracao.json"
ARQUIVO_PITOT_CAL  = CONFIG_DIR / "pitot_calibracao.json"
ARQUIVO_BATERIA_CAL = CONFIG_DIR / "bateria_calibracao.json"
ARQUIVO_PERFIS = CONFIG_DIR / "perfis.json"        # perfis de motor/helice
ARQUIVO_BANCO = CONFIG_DIR / "ensaios.db"

# Plot
PLOT_WINDOW_S = 30
SAMPLE_BUFFER_MAX = 200000

# Anomalias - limiares
ANOMALIA_QUEDA_EMPUXO_PCT = 15.0     # %
ANOMALIA_PICO_TORQUE_PCT = 30.0      # %
ANOMALIA_VARIACAO_RPM_PCT = 20.0     # %
ANOMALIA_PITOT_OSC_PCT   = 25.0      # variacao relativa de V no curto vs base

# Servidor remoto
PORTA_REMOTA_PADRAO = 8765
