"""
Geracao de relatorio PDF para um ensaio.

Usa matplotlib para renderizar graficos como PNG temporarios e
embute tudo num PDF via reportlab. Requer apenas pip install reportlab matplotlib.
"""
import io
import json
from pathlib import Path
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
)


def _grafico(x, y, xlabel, ylabel, titulo, x2=None, y2=None, label1=None, label2=None,
             markers=False):
    """Gera um PNG em memoria de um grafico simples."""
    fig, ax = plt.subplots(figsize=(7, 4), dpi=120)
    if markers:
        ax.plot(x, y, "o-", color="#1f6feb", label=label1, markersize=5)
    else:
        ax.plot(x, y, "-", color="#1f6feb", linewidth=1, label=label1)
    if x2 is not None and y2 is not None:
        ax.plot(x2, y2, "s--", color="#d05050", label=label2, markersize=5)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(titulo)
    ax.grid(True, alpha=0.3)
    if label1 or label2:
        ax.legend()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


def _tabela_style():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6feb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])


def _secao_sweep_estatico(story, df_sweep, h2, small):
    story.append(Paragraph("Tabela de pontos do sweep (patamares estaveis)", h2))
    cabecalho = ["#", "RPM", "T (g)", "Q (N.m)", "P_mec (W)", "T/P (g/W)", "C_T", "C_P", "FOM"]
    linhas = [cabecalho]
    for _, r in df_sweep.iterrows():
        linhas.append([
            int(r["idx"]),
            f"{r['rpm']:.0f}+/-{r['rpm_std']:.0f}",
            f"{r['empuxo_g']:.1f}+/-{r['empuxo_g_std']:.1f}",
            f"{r['torque_Nm']:.4f}",
            f"{r['p_mec_W']:.1f}",
            f"{r.get('T_por_P_g_por_W', r.get('T_por_P', 0)):.2f}",
            f"{r['C_T']:.4f}",
            f"{r['C_P']:.4f}",
            f"{r['FOM']:.3f}",
        ])
    t_sw = Table(linhas, repeatRows=1, hAlign="LEFT")
    t_sw.setStyle(_tabela_style())
    story.append(t_sw)
    story.append(Spacer(1, 0.4 * cm))

    sw = df_sweep.sort_values("rpm")
    t_p_col = "T_por_P_g_por_W" if "T_por_P_g_por_W" in sw.columns else "T_por_P"
    graficos = [
        (sw["rpm"], sw["empuxo_g"], "RPM", "Empuxo (g)", "Empuxo vs RPM"),
        (sw["rpm"], sw["torque_Nm"], "RPM", "Torque (N.m)", "Torque vs RPM"),
        (sw["rpm"], sw["p_mec_W"], "RPM", "P. mecanica (W)", "Potencia mecanica vs RPM"),
        (sw["rpm"], sw[t_p_col], "RPM", "T/P (g/W)", "Eficiencia propulsiva (T/P) vs RPM"),
        (sw["rpm"], sw["C_T"], "RPM", "C_T", "Coeficiente de empuxo C_T vs RPM"),
        (sw["rpm"], sw["FOM"], "RPM", "FOM", "Figure of Merit vs RPM"),
    ]
    for x, y, xl, yl, tit in graficos:
        buf = _grafico(x.values, y.values, xl, yl, tit, markers=True)
        story.append(Image(buf, width=15 * cm, height=8 * cm))
        story.append(Spacer(1, 0.2 * cm))

    story.append(PageBreak())


def _secao_sweep_dinamico(story, df_sweep, h2, small):
    story.append(Paragraph("Analise Dinamica - Patamares de J", h2))
    story.append(Paragraph(
        "Ensaio em modo dinamico (tunel de vento). "
        "Coeficientes calculados com escoamento incidente V>0. "
        "J = V/(n.D),  eta = J.C_T/C_P.",
        small))
    story.append(Spacer(1, 0.2 * cm))

    sw = df_sweep.sort_values("J") if "J" in df_sweep.columns else df_sweep

    cabecalho = ["#", "J", "V (m/s)", "RPM", "T (g)", "C_T", "C_P", "eta", "T/P (g/W)"]
    linhas = [cabecalho]
    for _, r in sw.iterrows():
        t_p = r.get("T_por_P_g_por_W", r.get("T_por_P", 0))
        eta_val = r.get("eta", 0.0)
        linhas.append([
            int(r["idx"]),
            f"{r.get('J', 0):.3f}",
            f"{r.get('V_med', 0):.2f}",
            f"{r['rpm']:.0f}",
            f"{r['empuxo_g']:.1f}",
            f"{r['C_T']:.4f}",
            f"{r['C_P']:.4f}",
            f"{eta_val:.3f}" if eta_val > 0 else "—",
            f"{t_p:.2f}",
        ])
    t_sw = Table(linhas, repeatRows=1, hAlign="LEFT")
    t_sw.setStyle(_tabela_style())
    story.append(t_sw)
    story.append(Spacer(1, 0.4 * cm))

    j_vals = sw["J"].values
    graficos_din = [
        (j_vals, sw["C_T"].values,      "J (razao de avanco)", "C_T",       "C_T vs J"),
        (j_vals, sw["C_P"].values,      "J (razao de avanco)", "C_P",       "C_P vs J"),
        (j_vals, sw["empuxo_g"].values, "J (razao de avanco)", "Empuxo (g)", "Empuxo vs J"),
    ]
    if "eta" in sw.columns:
        graficos_din.insert(2, (j_vals, sw["eta"].values, "J (razao de avanco)", "eta", "Eficiencia eta vs J"))
    for x, y, xl, yl, tit in graficos_din:
        buf = _grafico(x, y, xl, yl, tit, markers=True)
        story.append(Image(buf, width=15 * cm, height=8 * cm))
        story.append(Spacer(1, 0.2 * cm))

    story.append(PageBreak())


def _secao_uiuc_estatico(story, df_uiuc_compare, df_sweep, h2):
    story.append(Paragraph("Comparacao com banco UIUC (modo estatico)", h2))
    cabecalho = ["RPM", "C_T (ensaio)", "C_T (UIUC)", "Desvio C_T (%)",
                 "C_P (ensaio)", "C_P (UIUC)", "Desvio C_P (%)"]
    linhas = [cabecalho]
    for _, r in df_uiuc_compare.iterrows():
        linhas.append([
            f"{r['rpm_ensaio']:.0f}",
            f"{r['CT_ensaio']:.4f}",
            f"{r['CT_uiuc']:.4f}" if not np.isnan(r['CT_uiuc']) else "—",
            f"{r['CT_dev_pct']:+.1f}" if not np.isnan(r['CT_dev_pct']) else "—",
            f"{r['CP_ensaio']:.4f}",
            f"{r['CP_uiuc']:.4f}" if not np.isnan(r['CP_uiuc']) else "—",
            f"{r['CP_dev_pct']:+.1f}" if not np.isnan(r['CP_dev_pct']) else "—",
        ])
    t_u = Table(linhas, repeatRows=1, hAlign="LEFT")
    t_u.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6dffaf")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(t_u)
    story.append(Spacer(1, 0.3 * cm))

    if df_sweep is not None and not df_sweep.empty:
        sw = df_sweep.sort_values("rpm")
        cmp = df_uiuc_compare.sort_values("rpm_ensaio")
        buf = _grafico(
            sw["rpm"].values, sw["C_T"].values, "RPM", "C_T",
            "C_T - ensaio vs UIUC",
            cmp["rpm_ensaio"].values, cmp["CT_uiuc"].values,
            "Ensaio", "UIUC", markers=True,
        )
        story.append(Image(buf, width=15 * cm, height=8 * cm))


def _secao_uiuc_dinamico(story, df_uiuc_compare, df_sweep, h2):
    story.append(Paragraph("Comparacao com banco UIUC (modo dinamico)", h2))
    cabecalho = ["J", "C_T (ensaio)", "C_T (UIUC)", "Desvio C_T (%)",
                 "C_P (ensaio)", "C_P (UIUC)", "Desvio C_P (%)",
                 "eta (ensaio)", "eta (UIUC)", "Desvio eta (%)"]
    linhas = [cabecalho]
    for _, r in df_uiuc_compare.iterrows():
        def fmt(v, decimals=4):
            return f"{v:.{decimals}f}" if isinstance(v, float) and not np.isnan(v) else "—"
        linhas.append([
            fmt(r["J_ensaio"], 3),
            fmt(r["CT_ensaio"]), fmt(r["CT_uiuc"]),
            f"{r['CT_dev_pct']:+.1f}" if isinstance(r["CT_dev_pct"], float) and not np.isnan(r["CT_dev_pct"]) else "—",
            fmt(r["CP_ensaio"]), fmt(r["CP_uiuc"]),
            f"{r['CP_dev_pct']:+.1f}" if isinstance(r["CP_dev_pct"], float) and not np.isnan(r["CP_dev_pct"]) else "—",
            fmt(r["eta_ensaio"], 3), fmt(r.get("eta_uiuc", float("nan")), 3),
            f"{r['eta_dev_pct']:+.1f}" if isinstance(r.get("eta_dev_pct", float("nan")), float) and not np.isnan(r.get("eta_dev_pct", float("nan"))) else "—",
        ])
    t_u = Table(linhas, repeatRows=1, hAlign="LEFT")
    t_u.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6dffaf")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(t_u)
    story.append(Spacer(1, 0.3 * cm))

    if df_sweep is not None and not df_sweep.empty and "J" in df_sweep.columns:
        sw = df_sweep.sort_values("J")
        cmp = df_uiuc_compare.sort_values("J_ensaio")
        buf = _grafico(
            sw["J"].values, sw["C_T"].values, "J", "C_T",
            "C_T(J) - ensaio vs UIUC",
            cmp["J_ensaio"].values, cmp["CT_uiuc"].values,
            "Ensaio", "UIUC", markers=True,
        )
        story.append(Image(buf, width=15 * cm, height=8 * cm))
        story.append(Spacer(1, 0.2 * cm))

        if "eta_uiuc" in df_uiuc_compare.columns and "eta" in sw.columns:
            eta_ensaio = sw["eta"].fillna(0).values
            eta_uiuc_vals = cmp["eta_uiuc"].fillna(float("nan")).values
            buf2 = _grafico(
                sw["J"].values, eta_ensaio,
                "J", "eta",
                "eta(J) - ensaio vs UIUC",
                cmp["J_ensaio"].values, eta_uiuc_vals,
                "Ensaio", "UIUC", markers=True,
            )
            story.append(Image(buf2, width=15 * cm, height=8 * cm))


def gerar_relatorio_pdf(path_pdf,
                        metadados: dict,
                        cal_info: dict,
                        df_serie: pd.DataFrame,
                        df_sweep: pd.DataFrame,
                        df_uiuc_compare: pd.DataFrame = None,
                        observacoes: str = "",
                        modo_dinamico: bool = False):
    """
    Gera o relatorio PDF.

    Argumentos:
        path_pdf: arquivo de saida
        metadados: dict com helice/motor/bateria/condicoes/operador
        cal_info: dict com info da calibracao usada (ID, R^2, histerese)
        df_serie: DataFrame da serie temporal completa do ensaio
        df_sweep: DataFrame com os patamares extraidos
        df_uiuc_compare: comparacao com UIUC (opcional)
        observacoes: texto livre
        modo_dinamico: True para ensaio com Pitot/tunel de vento
    """
    path_pdf = Path(path_pdf)
    path_pdf.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(str(path_pdf), pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"],
                        textColor=colors.HexColor("#1f6feb"), spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                        textColor=colors.HexColor("#333"), spaceAfter=8)
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=9, textColor=colors.grey)

    story = []

    # ================ CAPA =================
    modo_label = "Dinamico (Pitot)" if modo_dinamico else "Estatico"
    story.append(Paragraph(f"Relatorio de Ensaio - Bancada de Empuxo [{modo_label}]", h1))
    story.append(Paragraph(
        f"Equipe Ceu Azul - Aerodesign &nbsp;&nbsp;|&nbsp;&nbsp; Gerado em {datetime.now():%d/%m/%Y %H:%M}",
        small))
    story.append(Spacer(1, 0.6 * cm))

    helice = metadados.get("helice", {})
    motor = metadados.get("motor", {})
    bateria = metadados.get("bateria", {})
    cond = metadados.get("condicoes", {})
    pitot = metadados.get("pitot", {})

    info_lines = [
        ["Helice", f"{helice.get('fabricante','')} {helice.get('modelo','')} "
                   f"{helice.get('diametro_in','?')}x{helice.get('passo_in','?')} pol"],
        ["Motor", f"{motor.get('modelo','')} - KV {motor.get('kv','?')} - "
                  f"{motor.get('pares_polos','?')} pares de polos"],
        ["Bateria", f"{bateria.get('cells','?')}S - {bateria.get('mAh','?')} mAh - "
                    f"V_inicial {bateria.get('V_inicial','?')} V"],
        ["ESC", metadados.get("esc", "")],
        ["Condicoes", f"T={cond.get('temp_C','?')} C, P={cond.get('pressao_hPa','?')} hPa, "
                     f"UR={cond.get('umidade_pct','?')}%, rho={cond.get('rho_kg_m3','?')} kg/m^3"],
        ["Tipo ensaio", modo_label],
        ["Operador", metadados.get("operador", "")],
        ["Data do ensaio", metadados.get("data", "")],
    ]
    if modo_dinamico and pitot:
        info_lines.append(["Pitot sensor", pitot.get("sensor", "—")])
        info_lines.append(["Pitot posicao", pitot.get("posicao", "—")])

    t_info = Table(info_lines, colWidths=[4.5 * cm, 11 * cm])
    t_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3fb")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 0.4 * cm))

    # ================ CALIBRACAO =================
    story.append(Paragraph("Calibracao utilizada", h2))
    cal_lines = [
        ["ID", cal_info.get("cal_id", "")],
        ["Empuxo - R^2", f"{cal_info.get('R2_emp', 0):.6f}"],
        ["Empuxo - histerese max", f"{cal_info.get('hist_emp', 0):.2f} g"],
        ["Empuxo - n pontos", str(cal_info.get("n_emp", 0))],
        ["Torque - R^2", f"{cal_info.get('R2_tor', 0):.6f}"],
        ["Torque - histerese max", f"{cal_info.get('hist_tor', 0):.2f} g"],
        ["Torque - n pontos", str(cal_info.get("n_tor", 0))],
        ["Qualidade", cal_info.get("qualidade", "")],
    ]
    if modo_dinamico and "pitot_cal_id" in cal_info:
        cal_lines.append(["Pitot cal ID", cal_info.get("pitot_cal_id", "—")])
        cal_lines.append(["Pitot pa/count", f"{cal_info.get('pitot_pa_per_count', 0):.4f}"])
        cal_lines.append(["Pitot k_corr", f"{cal_info.get('pitot_k_corr', 1.0):.4f}"])

    t_cal = Table(cal_lines, colWidths=[4.5 * cm, 11 * cm])
    t_cal.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3fb")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_cal)
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Nota: a histerese mecanica observada na calibracao representa a incerteza "
        "minima esperada na medicao de empuxo durante o ensaio.",
        small))
    story.append(PageBreak())

    # ================ SWEEP =================
    if df_sweep is not None and not df_sweep.empty:
        if modo_dinamico and "J" in df_sweep.columns:
            _secao_sweep_dinamico(story, df_sweep, h2, small)
        else:
            _secao_sweep_estatico(story, df_sweep, h2, small)

    # ================ COMPARACAO UIUC =================
    if df_uiuc_compare is not None and not df_uiuc_compare.empty:
        if modo_dinamico and "J_ensaio" in df_uiuc_compare.columns:
            _secao_uiuc_dinamico(story, df_uiuc_compare, df_sweep, h2)
        else:
            _secao_uiuc_estatico(story, df_uiuc_compare, df_sweep, h2)

    # ================ OBSERVACOES =================
    if observacoes:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("Observacoes", h2))
        story.append(Paragraph(observacoes.replace("\n", "<br/>"), body))

    doc.build(story)
    return path_pdf
