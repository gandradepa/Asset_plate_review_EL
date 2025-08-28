import os
import json
import re
import sqlite3
from functools import lru_cache
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify

app = Flask(
    __name__,
    template_folder=r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\Asset_plate_review_EL\review_asset_templates",
    static_folder=r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\Asset_plate_review_EL\review_asset_templates\static"
)

# --- Paths ---
JSON_DIR = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test\Output_jason_api"
IMG_DIR  = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test"

# --- SQLite DB ---
DB_PATH = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test\QR_codes.db"
SDI_TABLE = "sdi_dataset_EL"

# Dropdown sources
ASSET_GROUP_TABLE = "Asset_Group"     # mantido para futuro uso
ASSET_GROUP_COL   = "name"

ATTRIBUTE_TABLE    = "Attribute"
ATTRIBUTE_CODE_COL = "Code"           # e.g., 'Electrical'
ATTRIBUTE_VAL_COL  = "Attribute"      # valor humano

VALID_IMAGE_EXTS = ['.jpg', '.JPG', '.jpeg', '.JPEG', '.png', '.PNG']

# EL aceita apenas -0, -1, -2
SEQ_CHECK = ['-0', '-1', '-2']
SEQ_SHOW  = ['-0', '-1', '-2']

# JSON filename pattern: "<QR>_EL_<Building>.json"
JSON_NAME_RE = re.compile(r"^(\d+)_EL_(\d+(?:-\d+)?)\.json$")


def find_image(qr: str, building: str, seq_tag: str):
    """Find image by pattern: '<QR> <Building> EL - <seq>.<ext>'."""
    seq = seq_tag.replace('-', '').strip()
    base = f"{qr} {building} EL - {seq}"
    for ext in VALID_IMAGE_EXTS:
        candidate = os.path.join(IMG_DIR, base + ext)
        if os.path.exists(candidate):
            return os.path.basename(candidate)
    return None


@lru_cache(maxsize=1)
def _connectable():
    return os.path.exists(DB_PATH)


def _fetch_column_values(table: str, col: str):
    if not _connectable():
        return []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            query = f'SELECT "{col}" AS val FROM "{table}" WHERE "{col}" IS NOT NULL'
            cur.execute(query)
            vals = [str(r["val"]).strip() for r in cur.fetchall() if str(r["val"]).strip()]
            uniq = sorted(set(vals), key=lambda s: (s.lower(), s))
            return uniq
    except Exception as e:
        print(f"⚠️ DB fetch failed for {table}.{col}: {e}")
        return []


def _fetch_attribute_default_for_code(code_value: str) -> str:
    if not _connectable():
        return ""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            q = f'SELECT "{ATTRIBUTE_VAL_COL}" AS attr FROM "{ATTRIBUTE_TABLE}" WHERE "{ATTRIBUTE_CODE_COL}" = ? LIMIT 1'
            cur.execute(q, (code_value,))
            row = cur.fetchone()
            return (row["attr"] or "").strip() if row else ""
    except Exception as e:
        print(f"⚠️ DB default attribute fetch failed: {e}")
        return ""


def get_asset_group_options():
    return _fetch_column_values(ASSET_GROUP_TABLE, ASSET_GROUP_COL)


def get_attribute_options():
    return _fetch_column_values(ATTRIBUTE_TABLE, ATTRIBUTE_VAL_COL)


def _desc_from_ubc_or_branch(ubc_tag: str, branch: str) -> str:
    tag = (ubc_tag or "").strip() or (branch or "").strip()
    return f"Panel - {tag}" if tag else "Panel"


def _db_existing_cols(conn) -> list:
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{SDI_TABLE}")')
    return [r[1] for r in cur.fetchall()]  # name


def _db_upsert_el_row(conn, row: dict):
    """
    UPDATE por ("QR Code","Building"); se não achar, INSERT.
    Compatível sem PK/UNIQUE.
    """
    all_cols = [
        "QR Code","Building","Description","UBC Asset Tag","Branch Panel","Ampere",
        "Supply From","Volts","Location","Asset Group","Attribute","Approved"
    ]
    existing = _db_existing_cols(conn)

    # UPDATE
    set_cols = [c for c in all_cols if c in existing and c not in ("QR Code","Building")]
    if set_cols:
        set_part = ", ".join([f'"{c}"=?' for c in set_cols])
        sql_upd = f'''
            UPDATE "{SDI_TABLE}"
            SET {set_part}
            WHERE "QR Code"=? AND "Building"=?
        '''
        params_upd = [row.get(c, "") for c in set_cols] + [row.get("QR Code",""), row.get("Building","")]
        cur = conn.execute(sql_upd, params_upd)
        if cur.rowcount and cur.rowcount > 0:
            return "updated"

    # INSERT
    ins_cols = [c for c in all_cols if c in existing]
    placeholders = ",".join(["?"] * len(ins_cols))
    sql_ins = f'''
        INSERT INTO "{SDI_TABLE}" ({",".join(f'"{c}"' for c in ins_cols)})
        VALUES ({placeholders})
    '''
    conn.execute(sql_ins, [row.get(c, "") for c in ins_cols])
    return "inserted"


def _sync_db_from_structured(qr: str, building: str, sd: dict):
    """
    Prepara linha com as regras EL e grava em sdi_dataset_EL.
    Mapeia Approved: JSON 'True' -> DB '1'; caso contrário -> ''.
    """
    ubc = (sd.get("UBC Asset Tag") or "").strip()
    branch = (sd.get("Branch Panel") or "").strip()
    ubc_final = ubc if ubc else branch

    # default de Attribute (Electrical) se vazio
    attr = (sd.get("Attribute") or "").strip()
    if not attr:
        attr = _fetch_attribute_default_for_code("Electrical")

    # MAPA Approved: 'True' (JSON) -> '1' (DB); senão -> ''
    approved_db = "1" if (sd.get("Approved") or "").strip() == "True" else ""

    row = {
        "QR Code": qr,
        "Building": building,
        "Description": _desc_from_ubc_or_branch(ubc_final, branch),
        "UBC Asset Tag": ubc_final,
        "Branch Panel": branch,
        "Ampere": (sd.get("Ampere") or "").strip(),
        "Supply From": (sd.get("Supply From") or "").strip(),
        "Volts": (sd.get("Volts") or "").strip(),
        "Location": (sd.get("Location") or "").strip(),
        "Asset Group": (sd.get("Asset Group") or "").strip(),  # manter se existir na JSON
        "Attribute": attr,
        "Approved": approved_db,  # <- aqui gravamos '1' ou ''
    }

    with sqlite3.connect(DB_PATH) as conn:
        _db_upsert_el_row(conn, row)
        conn.commit()


def load_json_items():
    items = []
    for filename in os.listdir(JSON_DIR):
        if not filename.endswith(".json") or filename.endswith("_raw_ocr.json"):
            continue

        m = JSON_NAME_RE.match(filename)
        if not m:
            continue

        qr, building = m.groups()
        doc_id = filename[:-5]  # strip ".json"

        try:
            with open(os.path.join(JSON_DIR, filename), 'r', encoding='utf-8') as f:
                raw = json.load(f)

            data = raw.get("structured_data") or {}
            if not isinstance(data, dict):
                print(f"⚠️ Skipped {filename}: 'structured_data' is not a dict")
                continue

            # Garantir chaves EL
            data.setdefault("Description", "")
            data.setdefault("UBC Asset Tag", "")
            data.setdefault("Branch Panel", "")
            data.setdefault("Ampere", "")
            data.setdefault("Supply From", "")
            data.setdefault("Volts", "")
            data.setdefault("Location", "")
            data.setdefault("Attribute", "")
            data.setdefault("Flagged", "false")
            data.setdefault("Approved", "")

            # default de Attribute (Electrical)
            if not (data.get("Attribute") or "").strip():
                default_attr = _fetch_attribute_default_for_code("Electrical")
                if default_attr:
                    data["Attribute"] = default_attr

            # Description derivada
            data["Description"] = _desc_from_ubc_or_branch(data.get("UBC Asset Tag"), data.get("Branch Panel"))

            # Missed photos
            missing_tags = [tag for tag in SEQ_CHECK if not find_image(qr, building, tag)]
            missing_photo = len(missing_tags) > 0
            friendly_map = {'-0': 'Schedule/Header', '-1': 'UBC Asset Tag', '-2': 'Main Asset'}
            missing_friendly = ", ".join(friendly_map.get(tag, tag) for tag in missing_tags)

            items.append({
                "doc_id": doc_id,
                "qr_code": qr,
                "building": building,
                "asset_type": raw.get("asset_type", ""),
                "Flagged": data.get("Flagged", "false"),
                "Approved": data.get("Approved", ""),
                "Modified": raw.get("modified", False),
                "Missed Photo": "YES" if missing_photo else "NO",
                "Missing List": missing_friendly,
                "Photos Summary": f"{3 - len(missing_tags)}/3",
                **data
            })
        except Exception as e:
            print(f"❌ Error loading {filename}: {e}")
    return items


@app.route("/")
def index():
    flagged_filter = request.args.get("flagged")
    modified_filter = request.args.get("modified")
    missed_filter = request.args.get("missed")

    all_data = load_json_items()

    count_flagged = sum(1 for item in all_data if item.get("Flagged") == "true")
    count_modified = sum(1 for item in all_data if item.get("Modified"))
    count_missed = sum(1 for item in all_data if item.get("Missed Photo") == "YES")

    data = all_data
    if flagged_filter == "true" and modified_filter == "true":
        data = [item for item in data if item.get("Flagged") == "true" and item.get("Modified")]
    elif flagged_filter == "true":
        data = [item for item in data if item.get("Flagged") == "true"]
    elif modified_filter == "true":
        data = [item for item in data if item.get("Modified")]

    if missed_filter == "true":
        data = [item for item in data if item.get("Missed Photo") == "YES"]

    return render_template(
        "dashboard.html",
        data=data,
        warn_missing=True,
        flagged_filter=flagged_filter,
        modified_filter=modified_filter,
        missed_filter=missed_filter,
        count_flagged=count_flagged,
        count_modified=count_modified,
        count_missed=count_missed
    )


@app.route("/review/<doc_id>")
def review(doc_id):
    json_path = os.path.join(JSON_DIR, f"{doc_id}.json")
    if not os.path.exists(json_path):
        return "Not found", 404

    m = JSON_NAME_RE.match(f"{doc_id}.json")
    if not m:
        return "Bad ID", 400

    qr, building = m.groups()
    with open(json_path, 'r', encoding='utf-8') as f:
        loaded = json.load(f)

    data = loaded.get("structured_data", {}) or {}

    for k in ["Description","UBC Asset Tag","Branch Panel","Ampere","Supply From","Volts","Location",
              "Attribute","Approved","Flagged"]:
        data.setdefault(k, "" if k not in ("Flagged",) else "false")

    if not (data.get("Attribute") or "").strip():
        default_attr = _fetch_attribute_default_for_code("Electrical")
        if default_attr:
            data["Attribute"] = default_attr

    data["Description"] = _desc_from_ubc_or_branch(data.get("UBC Asset Tag"), data.get("Branch Panel"))

    images = {}
    for tag in SEQ_SHOW:
        filename = find_image(qr, building, tag)
        images[tag] = {"exists": bool(filename), "url": url_for('serve_image', filename=filename) if filename else None}

    attribute_options = get_attribute_options()

    return render_template(
        "review.html",
        doc_id=doc_id,
        qr_code=qr,
        building=building,
        asset_type=loaded.get("asset_type", ""),
        data=data,
        images=images,
        attribute_options=attribute_options
    )


@app.route("/review/<doc_id>", methods=["POST"])
def save_review(doc_id):
    """
    Salva JSON + sincroniza linha em sdi_dataset_EL (UPDATE→INSERT).
    No DB, Approved é gravado como '1' se JSON == 'True', senão ''.
    """
    json_path = os.path.join(JSON_DIR, f"{doc_id}.json")
    if not os.path.exists(json_path):
        return "Not found", 404

    m = JSON_NAME_RE.match(f"{doc_id}.json")
    if not m:
        return "Bad ID", 400

    qr, building = m.groups()

    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    structured = json_data.get("structured_data", {})
    if not isinstance(structured, dict):
        structured = {}
        json_data["structured_data"] = structured

    # Garantir chaves
    for k in ["Description","UBC Asset Tag","Branch Panel","Ampere","Supply From","Volts","Location",
              "Attribute","Approved","Flagged"]:
        structured.setdefault(k, "" if k not in ("Flagged",) else "false")

    # Flagged
    new_flagged = "true" if request.form.get("Flagged") == "on" else "false"
    if structured.get("Flagged", "false") != new_flagged:
        json_data["modified"] = True
    structured["Flagged"] = new_flagged

    # Atualiza campos enviados (exceto derivados Approved/Description)
    skip_fields = {"Flagged","Description","Approved"}
    for field in list(structured.keys()):
        if field in skip_fields:
            continue
        form_value = request.form.get(field, "")
        if structured.get(field, "") != form_value:
            json_data["modified"] = True
        structured[field] = form_value

    # Captura novos campos (se surgirem)
    for field, form_value in request.form.items():
        if field in {"Flagged","action","Description","dashboard_query"}:
            continue
        if field not in structured:
            structured[field] = form_value
            json_data["modified"] = True

    # Recalcula Description
    structured["Description"] = _desc_from_ubc_or_branch(structured.get("UBC Asset Tag"), structured.get("Branch Panel"))

    # Persiste JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=4)

    # === SYNC DB: UPDATE→INSERT (Approved: 'True' -> '1') ===
    try:
        _sync_db_from_structured(qr, building, structured)
    except Exception as e:
        print(f"⚠️ Falha ao sincronizar DB (save_review): {e}")

    # Navegação
    all_files = sorted(
        f for f in os.listdir(JSON_DIR)
        if f.endswith(".json") and not f.endswith("_raw_ocr.json") and JSON_NAME_RE.match(f)
    )
    current_name = f"{doc_id}.json"
    try:
        current_index = all_files.index(current_name)
    except ValueError:
        dash_q = request.form.get("dashboard_query", "")
        if (dash_q or "").startswith("?"):
            return redirect(url_for("index") + dash_q)
        return redirect(url_for("index"))

    action = request.form.get("action")
    if action == "save_next" and current_index + 1 < len(all_files):
        next_doc = all_files[current_index + 1][:-5]
        return redirect(url_for("review", doc_id=next_doc))
    elif action == "save_prev" and current_index > 0:
        prev_doc = all_files[current_index - 1][:-5]
        return redirect(url_for("review", doc_id=prev_doc))

    dash_q = request.form.get("dashboard_query", "")
    if (dash_q or "").startswith("?"):
        return redirect(url_for("index") + dash_q)
    return redirect(url_for("index"))


@app.route("/toggle_approved/<doc_id>", methods=["POST"])
def toggle_approved(doc_id):
    """
    Alterna Approved no JSON e sincroniza o mesmo valor na sdi_dataset_EL (UPDATE→INSERT).
    No DB, Approved é gravado como '1' se JSON == 'True', senão ''.
    """
    json_path = os.path.join(JSON_DIR, f"{doc_id}.json")
    if not os.path.exists(json_path):
        return jsonify({"success": False, "error": "Not found"}), 404

    m = JSON_NAME_RE.match(f"{doc_id}.json")
    if not m:
        return jsonify({"success": False, "error": "Bad ID"}), 400

    qr, building = m.groups()

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)

        structured = json_data.get("structured_data", {})
        if not isinstance(structured, dict):
            structured = {}
            json_data["structured_data"] = structured

        cur_val = structured.get("Approved", "")
        new_val = "True" if cur_val == "" else ""
        structured["Approved"] = new_val
        json_data["structured_data"] = structured

        # Persiste JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        # === SYNC DB: UPDATE→INSERT (Approved: 'True' -> '1') ===
        try:
            _sync_db_from_structured(qr, building, structured)
        except Exception as e:
            print(f"⚠️ Falha ao sincronizar DB (toggle_approved): {e}")

        return jsonify({"success": True, "new_value": structured["Approved"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(IMG_DIR, filename)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
