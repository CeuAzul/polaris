"""
Banco SQLite simples para indexar ensaios e permitir comparacao
entre eles. Cada ensaio guarda metadados, caminho do CSV e sumario.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime


def conectar(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path):
    """Cria as tabelas se nao existirem."""
    conn = conectar(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ensaios (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            data_iso        TEXT NOT NULL,
            csv_path        TEXT NOT NULL,
            metadados_json  TEXT NOT NULL,
            cal_id          TEXT,
            helice          TEXT,
            motor           TEXT,
            duracao_s       REAL,
            empuxo_max_g    REAL,
            torque_max_Nm  REAL,
            rpm_max         REAL,
            n_patamares     INTEGER,
            observacoes     TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sweep_pontos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ensaio_id   INTEGER NOT NULL,
            idx         INTEGER,
            t_ini       REAL,
            t_fim       REAL,
            empuxo_g    REAL,
            empuxo_g_std REAL,
            forca_torque_g REAL,
            torque_Nm  REAL,
            rpm         REAL,
            rpm_std     REAL,
            p_mec_W     REAL,
            T_por_P     REAL,
            C_T         REAL,
            C_P         REAL,
            C_Q         REAL,
            FOM         REAL,
            FOREIGN KEY (ensaio_id) REFERENCES ensaios(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()


def inserir_ensaio(path_db, csv_path, metadados, cal_id, sumario):
    """Insere um ensaio. Retorna id criado."""
    conn = conectar(path_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ensaios
            (data_iso, csv_path, metadados_json, cal_id, helice, motor,
             duracao_s, empuxo_max_g, torque_max_Nm, rpm_max, n_patamares, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(timespec="seconds"),
        str(csv_path),
        json.dumps(metadados, ensure_ascii=False),
        cal_id,
        metadados.get("helice", {}).get("modelo", "") if isinstance(metadados.get("helice"), dict) else "",
        metadados.get("motor", {}).get("modelo", "") if isinstance(metadados.get("motor"), dict) else "",
        sumario.get("duracao_s", 0.0),
        sumario.get("empuxo_max_g", 0.0),
        sumario.get("torque_max_Nm", 0.0),
        sumario.get("rpm_max", 0.0),
        sumario.get("n_patamares", 0),
        metadados.get("observacoes", ""),
    ))
    ensaio_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ensaio_id


def inserir_sweep_pontos(path_db, ensaio_id, df_sweep):
    """Insere os pontos do sweep de um ensaio."""
    if df_sweep is None or df_sweep.empty:
        return
    conn = conectar(path_db)
    cur = conn.cursor()
    for _, row in df_sweep.iterrows():
        cur.execute("""
            INSERT INTO sweep_pontos
                (ensaio_id, idx, t_ini, t_fim, empuxo_g, empuxo_g_std,
                 forca_torque_g, torque_Nm, rpm, rpm_std, p_mec_W, T_por_P,
                 C_T, C_P, C_Q, FOM)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ensaio_id,
            int(row["idx"]),
            float(row["t_ini"]), float(row["t_fim"]),
            float(row["empuxo_g"]), float(row["empuxo_g_std"]),
            float(row["forca_torque_g"]), float(row["torque_Nm"]),
            float(row["rpm"]), float(row["rpm_std"]),
            float(row["p_mec_W"]), float(row["T_por_P_g_por_W"]),
            float(row["C_T"]), float(row["C_P"]), float(row["C_Q"]), float(row["FOM"]),
        ))
    conn.commit()
    conn.close()


def listar_ensaios(path_db, filtro_helice=None, filtro_motor=None):
    """Lista ensaios filtrados, ordenados por data desc."""
    conn = conectar(path_db)
    cur = conn.cursor()
    sql = "SELECT * FROM ensaios WHERE 1=1"
    args = []
    if filtro_helice:
        sql += " AND helice LIKE ?"
        args.append(f"%{filtro_helice}%")
    if filtro_motor:
        sql += " AND motor LIKE ?"
        args.append(f"%{filtro_motor}%")
    sql += " ORDER BY data_iso DESC"
    cur.execute(sql, args)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_sweep_pontos(path_db, ensaio_id):
    """Retorna os pontos de sweep de um ensaio."""
    conn = conectar(path_db)
    cur = conn.cursor()
    cur.execute("SELECT * FROM sweep_pontos WHERE ensaio_id = ? ORDER BY idx", (ensaio_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def deletar_ensaio(path_db, ensaio_id):
    conn = conectar(path_db)
    cur = conn.cursor()
    cur.execute("DELETE FROM sweep_pontos WHERE ensaio_id = ?", (ensaio_id,))
    cur.execute("DELETE FROM ensaios WHERE id = ?", (ensaio_id,))
    conn.commit()
    conn.close()