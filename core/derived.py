"""
Calculos derivados a partir das medidas brutas.

Conversoes principais:
    RPM_eletrico = pulsos / dt[s] * 60
    RPM_mecanico = RPM_eletrico / pares_de_polos
    omega [rad/s] = RPM_mec * 2pi / 60
    Empuxo [N]   = empuxo[g] * g / 1000
    Torque [N.m] = forca_torque[g] * g / 1000 * braco[m]
    P_mec [W]    = omega * Torque
    T/P [g/W]    = empuxo[g] / P_mec[W]

Coeficientes adimensionais:
    n [rev/s] = RPM_mec / 60
    C_T = T / (rho * n^2 * D^4)
    C_P = P_mec / (rho * n^3 * D^5)
    C_Q = Q / (rho * n^2 * D^5)

Em ensaio estatico (J = 0):
    FOM = C_T^1.5 / (C_P * sqrt(2))   (figure of merit estatico)

Em ensaio dinamico (V_inflow > 0):
    J = V / (n * D)                   (razao de avanco)
    eta = J * C_T / C_P               (eficiencia da helice)
"""
import math
import numpy as np

from config import GRAVIDADE, BRACO_TORQUE_M


# Velocidade abaixo desta e considerada estatica (J~0). Acima, calcula J/eta.
LIMIAR_DINAMICO_MS = 0.5


# ------------------------------------------------------------
# Densidade do ar
# ------------------------------------------------------------
def densidade_ar(temp_C: float, pressao_hPa: float, umidade_pct: float = 50.0) -> float:
    """
    Densidade do ar umido (kg/m^3) a partir de T, P e umidade relativa.
    Formula CIPM-2007 simplificada (precisao tipica ±0.1%).
    """
    T = temp_C + 273.15  # K
    P = pressao_hPa * 100.0  # Pa
    UR = max(0.0, min(100.0, umidade_pct)) / 100.0

    # Pressao de saturacao do vapor (Tetens)
    Psat = 611.2 * math.exp(17.62 * temp_C / (243.12 + temp_C))  # Pa
    Pv = UR * Psat                                # pressao parcial do vapor
    Pd = P - Pv                                   # pressao parcial seca

    Rd = 287.058   # J/(kg.K) ar seco
    Rv = 461.495   # J/(kg.K) vapor d'agua

    rho = (Pd / (Rd * T)) + (Pv / (Rv * T))
    return rho


# ------------------------------------------------------------
# RPM
# ------------------------------------------------------------
def rpm_de_pulsos(pulsos: int, dt_us: int, pares_polos: int) -> float:
    """Converte (pulsos, dt) -> RPM mecanico.

    O ESC Hobbywing Platinum emite 1 pulso por comutacao eletrica.
    Cada revolucao mecanica do motor passa por (pares_polos)
    comutacoes eletricas.

    Logo:
        Pulsos por revolucao mecanica = pares_polos
        RPM_mec = (pulsos / dt_s × 60) / pares_polos

    Validado empiricamente comparando empuxo medido com banco UIUC
    para APC 16x8E com motor X4120 (7 pares de polos), e contra
    tacometro optico TC-5035.
    """
    if dt_us <= 0 or pares_polos <= 0:
        return 0.0
    pulsos_por_segundo = pulsos / (dt_us * 1e-6)
    return pulsos_por_segundo * 60.0 / pares_polos


# ------------------------------------------------------------
# Potencia e eficiencia
# ------------------------------------------------------------
def potencia_mecanica_W(rpm_mec: float, forca_torque_g: float, braco_m: float = BRACO_TORQUE_M) -> float:
    """P_mec [W] = omega [rad/s] * Q [N.m]"""
    if rpm_mec <= 0:
        return 0.0
    omega = rpm_mec * 2 * math.pi / 60.0
    Q = (forca_torque_g / 1000.0) * GRAVIDADE * braco_m   # N.m
    return omega * Q


def empuxo_especifico_g_por_W(empuxo_g: float, p_mec_W: float) -> float:
    """g/W. Util para comparar eficiencia em hover."""
    if p_mec_W <= 0.001:
        return 0.0
    return empuxo_g / p_mec_W


# ------------------------------------------------------------
# Razao de avanco e eficiencia da helice
# ------------------------------------------------------------
def razao_avanco_J(V_ms: float, rpm_mec: float, D_m: float) -> float:
    """
    J = V / (n * D), onde n = RPM/60 (rev/s).
    Para RPM ou D <= 0 retorna 0 (caso degenerado).
    """
    if rpm_mec <= 0 or D_m <= 0:
        return 0.0
    n_rps = rpm_mec / 60.0
    return float(V_ms) / (n_rps * D_m)


def eficiencia_helice(J: float, C_T: float, C_P: float) -> float:
    """
    eta = J * C_T / C_P. So faz sentido para J > 0 e C_P > 0.
    Em J=0 (estatico) retorna 0 - use FOM nesse caso.
    """
    if J <= 0 or C_P <= 0:
        return 0.0
    return float(J * C_T / C_P)


# ------------------------------------------------------------
# Coeficientes adimensionais
# ------------------------------------------------------------
def coeficientes(empuxo_g: float, forca_torque_g: float, rpm_mec: float,
                 D_m: float, rho: float, braco_m: float = BRACO_TORQUE_M,
                 V_inflow_ms: float = 0.0) -> dict:
    """
    Calcula C_T, C_P, C_Q, FOM, J, eta.

    Quando V_inflow_ms > LIMIAR_DINAMICO_MS, calcula J e eta (modo dinamico).
    FOM continua sendo retornado mas so e fisicamente significativo em J~0.

    Retorna dict ou zeros se RPM muito baixo.
    """
    base = {"C_T": 0.0, "C_P": 0.0, "C_Q": 0.0, "FOM": 0.0, "J": 0.0, "eta": 0.0}
    if rpm_mec < 100 or D_m <= 0 or rho <= 0:
        return base

    n_rps = rpm_mec / 60.0
    T_N = (empuxo_g / 1000.0) * GRAVIDADE
    Q_Nm = (forca_torque_g / 1000.0) * GRAVIDADE * braco_m
    P_mec = potencia_mecanica_W(rpm_mec, forca_torque_g, braco_m)

    den_T = rho * (n_rps ** 2) * (D_m ** 4)
    den_P = rho * (n_rps ** 3) * (D_m ** 5)
    den_Q = rho * (n_rps ** 2) * (D_m ** 5)

    C_T = T_N / den_T if den_T > 0 else 0.0
    C_P = P_mec / den_P if den_P > 0 else 0.0
    C_Q = Q_Nm / den_Q if den_Q > 0 else 0.0

    # FOM (estatico): se C_T <= 0 ou C_P <= 0, indefinido
    if C_T > 0 and C_P > 0:
        FOM = (C_T ** 1.5) / (C_P * math.sqrt(2.0))
    else:
        FOM = 0.0

    # J e eta no modo dinamico
    J = razao_avanco_J(V_inflow_ms, rpm_mec, D_m)
    eta = eficiencia_helice(J, C_T, C_P) if V_inflow_ms > LIMIAR_DINAMICO_MS else 0.0

    return {"C_T": C_T, "C_P": C_P, "C_Q": C_Q, "FOM": FOM, "J": J, "eta": eta}


# ------------------------------------------------------------
# Conversao de polegadas para metros
# ------------------------------------------------------------
def polegadas_para_m(valor_in: float) -> float:
    return valor_in * 0.0254
