#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loader EL: JSON -> SQLite (sdi_dataset_EL)
Estratégia: UPDATE por ("QR Code","Building"); se 0 linhas, faz INSERT.
NÃO requer PRIMARY KEY ou UNIQUE.

Melhorias:
- Fallback: se "UBC Asset Tag" vazio, usar "Branch Panel".
- Description = "Panel - <UBC Asset Tag ou Branch Panel>"; se ambos vazios -> "Panel".
- Attribute default via tabela Attribute onde Code = "Electrical".
- Relatório final com contagem de JSONs processados e amostra da tabela.

Uso (PowerShell):
  python "S:\\MaintOpsPlan\\AssetMgt\\Asset Management Process\\Database\\8. New Assets\\Git_control\\Asset_plate_review_EL\\load_el_json_to_sdi_dataset_EL_update_insert_v2.py"
"""

import os
import re
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List

# === PATHS (ajuste se necessário) ===
DB_PATH  = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test\QR_codes.db"
JSON_DIR = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test\Output_jason_api"

TABLE = "sdi_dataset_EL"
# Padrão de nome: <QR>_EL_<Building>.json
JSON_NAME_RE = re.compile(r"^(\d+)_EL_(\d+(?:-\d+)?)\.json$", re.IGNORECASE)

# Colunas esperadas na tabela (conforme seu PRAGMA)
COLS = [
    "QR Code",
    "Building",
    "Description",
    "UBC Asset Tag",
    "Branch Panel",
    "Ampere",
    "Supply From",
    "Volts",
    "Location",
    "Asset Group",
    "Attribute",
    "Approved",
]

def compute_description(ubc_or_branch: str) -> str:
    tag = (ubc_or_branch or "").strip()
    return f"Panel - {tag}" if tag else "Panel"

def fetch_default_attribute(conn: sqlite3.Connection) -> str:
    """
    Busca na tabela Attribute o valor da coluna 'Attribute' quando Code = 'Electrical'
    """
    try:
        cur = conn.cursor()
        cur.execute('SELECT "Attribute" FROM "Attribute" WHERE "Code" = ? LIMIT 1', ("Electrical",))
        row = cur.fetchone()
        return (row[0] or "").strip() if row else ""
    except Exception:
        return ""

def check_table_columns(conn: sqlite3.Connection) -> List[str]:
    """
    Retorna as colunas da tabela alvo e alerta se algo essencial estiver faltando.
    """
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{TABLE}")')
    cols = [r[1] for r in cur.fetchall()]  # r[1] = name
    missing = [c for c in COLS if c not in cols]
    if missing:
        print(f"⚠️ Atenção: a tabela '{TABLE}' não possui estas colunas: {missing}")
        print("   O script continuará, mas essas colunas ficarão vazias no INSERT.")
    return cols

def upsert_row_update_then_insert(conn: sqlite3.Connection, row: Dict[str, Any], existing_cols: List[str]) -> str:
    """
    Tenta UPDATE por (QR Code, Building). Se 0 linhas, faz INSERT.
    Retorna 'updated' ou 'inserted'.
    """
    # UPDATE: apenas colunas existentes e não-chave
    set_cols = [c for c in COLS if c in existing_cols and c not in ("QR Code", "Building")]
    if set_cols:
        set_part = ", ".join([f'"{c}"=?' for c in set_cols])
        sql_upd = f'''
            UPDATE "{TABLE}"
            SET {set_part}
            WHERE "QR Code"=? AND "Building"=?
        '''
        params_upd = [row.get(c, "") for c in set_cols] + [row.get("QR Code", ""), row.get("Building", "")]
        cur = conn.execute(sql_upd, params_upd)
        if cur.rowcount and cur.rowcount > 0:
            return "updated"

    # INSERT: apenas colunas existentes
    ins_cols = [c for c in COLS if c in existing_cols]
    placeholders = ",".join(["?"] * len(ins_cols))
    sql_ins = f'''
        INSERT INTO "{TABLE}" ({",".join(f'"{c}"' for c in ins_cols)})
        VALUES ({placeholders})
    '''
    conn.execute(sql_ins, [row.get(c, "") for c in ins_cols])
    return "inserted"

def build_row_from_json(qr_code: str, building: str, sd: Dict[str, Any], default_attr: str) -> Dict[str, Any]:
    """
    Monta o dicionário de linha com defaults e regras EL.
    - UBC Asset Tag: se vazio, usar Branch Panel.
    - Description: baseado no valor final do UBC/Branch.
    """
    ubc_raw = (sd.get("UBC Asset Tag") or "").strip()
    branch  = (sd.get("Branch Panel") or "").strip()
    ubc = ubc_raw if ubc_raw else branch

    row = {
        "QR Code": qr_code,
        "Building": building,
        "Description": compute_description(ubc),
        "UBC Asset Tag": ubc,  # já com fallback
        "Branch Panel": branch,
        "Ampere": (sd.get("Ampere") or "").strip(),
        "Supply From": (sd.get("Supply From") or "").strip(),
        "Volts": (sd.get("Volts") or "").strip(),
        "Location": (sd.get("Location") or "").strip(),
        "Asset Group": (sd.get("Asset Group") or "").strip(),  # manter se vier
        "Attribute": (sd.get("Attribute") or "").strip(),
        "Approved": (sd.get("Approved") or "").strip(),
    }
    if not row["Attribute"] and default_attr:
        row["Attribute"] = default_attr
    return row

def preview_rows(conn: sqlite3.Connection, limit: int = 10):
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT "QR Code","Building","UBC Asset Tag","Branch Panel","Description","Attribute","Approved" FROM "{TABLE}" ORDER BY "QR Code","Building" LIMIT ?', (limit,))
        rows = cur.fetchall()
        print("\n📋 Amostra das linhas em sdi_dataset_EL:")
        for i, r in enumerate(rows, 1):
            print(f"[{i}] QR={r[0]} | Bld={r[1]} | UBC='{r[2]}' | Branch='{r[3]}' | Desc='{r[4]}' | Attr='{r[5]}' | Approved='{r[6]}'")
    except Exception as e:
        print(f"⚠️ Não foi possível gerar amostra: {e}")

def main():
    db = Path(DB_PATH)
    if not db.exists():
        print(f"❌ DB não encontrado: {DB_PATH}")
        return
    print(f"✅ Usando DB: {DB_PATH}")

    json_dir = Path(JSON_DIR)
    if not json_dir.exists():
        print(f"❌ Pasta JSON não encontrada: {JSON_DIR}")
        return

    # Seleciona apenas JSONs *_EL_*.json
    all_jsons = [fn for fn in os.listdir(json_dir) if fn.lower().endswith(".json") and not fn.endswith("_raw_ocr.json")]
    files = [fn for fn in all_jsons if JSON_NAME_RE.match(fn)]
    files.sort()

    print(f"🧩 JSONs no diretório: {len(all_jsons)} | JSONs EL compatíveis: {len(files)}")
    if not files:
        print("⚠️ Nenhum JSON *_EL_*.json encontrado no diretório informado.")
        return

    updated = inserted = failed = 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        existing_cols = check_table_columns(conn)
        default_attr = fetch_default_attribute(conn)

        for fn in files:
            m = JSON_NAME_RE.match(fn)
            qr_code, building = m.groups()

            fpath = json_dir / fn
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    doc = json.load(f)
            except Exception as e:
                print(f"⚠️ Erro lendo {fn}: {e}")
                failed += 1
                continue

            sd = doc.get("structured_data") or {}
            if not isinstance(sd, dict):
                print(f"⚠️ structured_data inválido em {fn}, pulando.")
                failed += 1
                continue

            row = build_row_from_json(qr_code, building, sd, default_attr)

            try:
                action = upsert_row_update_then_insert(conn, row, existing_cols)
                if action == "updated":
                    updated += 1
                else:
                    inserted += 1
            except Exception as e:
                print(f"❌ Falha ao inserir/atualizar {fn}: {e}")
                failed += 1

        conn.commit()

        # Resumo final
        cur = conn.cursor()
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{TABLE}"')
            total = cur.fetchone()[0]
        except Exception:
            total = "desconhecido"

        print("—" * 60)
        print(f"✅ Concluído.")
        print(f"   Inseridos : {inserted}")
        print(f"   Atualizados: {updated}")
        print(f"   Falhas    : {failed}")
        print(f"📊 Total atual em {TABLE}: {total}")

        preview_rows(conn, limit=10)

if __name__ == "__main__":
    main()
