#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import sqlite3
from functools import lru_cache
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify

# ---------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "review_asset_templates"),
    static_folder=os.path.join(BASE_DIR, "review_asset_templates", "static")
)

# ---------------------------------------------------------------------
# Paths - read from ENV or fallback to defaults
# ---------------------------------------------------------------------
JSON_DIR = os.environ.get("JSON_DIR", "/home/developer/Output_jason_api")
IMG_DIR = os.environ.get("IMG_DIR", "/home/developer/Capture_photos_upload")
DB_PATH = os.environ.get("DB_PATH", "/home/developer/asset_capture_app_dev/data/QR_codes.db")

SDI_TABLE = "sdi_dataset_EL"

# Dropdown source defaults
ATTRIBUTE_TABLE = "Attribute"
ATTRIBUTE_CODE_COL = "Code"       # filter by 'Electrical'
ATTRIBUTE_VAL_COL = "Attribute"   # default value to use

ASSET_GROUP_TABLE = "Asset_Group"
ASSET_GROUP_NAME_COL = "Name"     # values that contain "Panels"
ASSET_GROUP_DEFAULT = "Panels"

VALID_IMAGE_EXTS = ['.jpg', '.JPG', '.jpeg', '.JPEG', '.png', '.PNG']

# ---------------------------------------------------------------------
# Photo rules
# ---------------------------------------------------------------------
# -0 = Asset Plate (optional), -1 = UBC Asset Tag (required), -2 = Panel Schedule (required)
ALL_SHOW = ['-0', '-1', '-2']
REQUIRED = ['-1', '-2']
SEQ_SHOW = ALL_SHOW[:]

# JSON filename pattern: "<QR>_EL_<Building>.json" (ex.: 0000123456_EL_314-1.json)
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


def _fetch_attribute_default_for_code(code_value: str) -> str:
    """Fetch default Attribute value for a given code (e.g., 'Electrical')."""
    if not _connectable():
        return ""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            q = (
                f'SELECT "{ATTRIBUTE_VAL_COL}" AS attr '
                f'FROM "{ATTRIBUTE_TABLE}" '
                f'WHERE "{ATTRIBUTE_CODE_COL}" = ? LIMIT 1'
            )
            cur.execute(q, (code_value,))
            row = cur.fetchone()
            return (row["attr"] or "").strip() if row else ""
    except Exception as e:
        print(f"[WARN] DB default attribute fetch failed: {e}")
        return ""


def _fetch_asset_group_options_panels() -> list:
    """
    Fetch Asset Group options from Asset_Group.Name filtering only values containing 'Panels' (case-insensitive).
    """
    opts = []
    if not _connectable():
        return [ASSET_GROUP_DEFAULT]
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            q = (
                f'SELECT "{ASSET_GROUP_NAME_COL}" AS name '
                f'FROM "{ASSET_GROUP_TABLE}" '
                f'WHERE "{ASSET_GROUP_NAME_COL}" LIKE ? COLLATE NOCASE '
                f'ORDER BY "{ASSET_GROUP_NAME_COL}"'
            )
            cur.execute(q, ("%Panels%",))
            opts = [(r["name"] or "").strip() for r in cur.fetchall() if (r["name"] or "").strip()]
    except Exception as e:
        print(f"[WARN] DB asset group fetch failed: {e}")
    # Ensure 'Panels' exists and is first as default
    if ASSET_GROUP_DEFAULT not in opts:
        opts = [ASSET_GROUP_DEFAULT] + opts
    return opts or [ASSET_GROUP_DEFAULT]


def _desc_from_ubc_or_branch(ubc_tag: str, branch: str) -> str:
    tag = (ubc_tag or "").strip() or (branch or "").strip()
    return f"Panel - {tag}" if tag else "Panel"


def _db_existing_cols(conn) -> list:
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{SDI_TABLE}")')
    return [r[1] for r in cur.fetchall()]


def _db_upsert_el_row(conn, row: dict):
    """
    UPDATE by ("QR Code","Building"); if not found, INSERT.
    Works without PK/UNIQUE.
    """
    all_cols = [
        "QR Code", "Building", "Description", "UBC Asset Tag", "Branch Panel", "Ampere",
        "Supply From", "Volts", "Location", "Asset Group", "Attribute", "Approved"
    ]
    existing = _db_existing_cols(conn)

    # UPDATE first
    set_cols = [c for c in all_cols if c in existing and c not in ("QR Code", "Building")]
    if set_cols:
        set_part = ", ".join([f'"{c}"=?' for c in set_cols])
        sql_upd = f'''
            UPDATE "{SDI_TABLE}"
               SET {set_part}
             WHERE "QR Code"=? AND "Building"=?
        '''
        params_upd = [row.get(c, "") for c in set_cols] + [row.get("QR Code", ""), row.get("Building", "")]
        cur = conn.execute(sql_upd, params_upd)
        if cur.rowcount and cur.rowcount > 0:
            return "updated"

    # INSERT if UPDATE didn't happen
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
    Prepare row and upsert into sdi_dataset_EL.
    Maps Approved: JSON 'True' -> DB '1'; otherwise ''.
    """
    ubc = (sd.get("UBC Asset Tag") or "").strip()
    branch = (sd.get("Branch Panel") or "").strip()  # kept for Description, hidden in UI
    ubc_final = ubc if ubc else branch

    attr = "Electrical"

    approved_db = "1" if (sd.get("Approved") or "").strip() == "True" else ""

    row = {
        "QR Code": qr,
        "Building": building,
        "Description": _desc_from_ubc_or_branch(ubc_final, branch),
        "UBC Asset Tag": ubc_final,
        "Branch Panel": branch,  # stays in DB (hidden in UI)
        "Ampere": (sd.get("Ampere") or "").strip(),
        "Supply From": (sd.get("Supply From") or "").strip(),
        "Volts": (sd.get("Volts") or "").strip(),
        "Location": (sd.get("Location") or "").strip(),
        "Asset Group": (sd.get("Asset Group") or "").strip(),
        "Attribute": attr,
        "Approved": approved_db,
    }

    with sqlite3.connect(DB_PATH) as conn:
        _db_upsert_el_row(conn, row)
        conn.commit()


def load_json_items():
    """
    Load all JSONs; compute derived UI fields.
    """
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
                print(f"[WARN] Skipped {filename}: 'structured_data' is not a dict")
                continue

            # Ensure keys
            keep_blank = [
                "UBC Asset Tag", "Branch Panel", "Ampere", "Supply From", "Volts", "Location",
                "Attribute", "Approved", "Asset Group"
            ]
            for k in keep_blank:
                data.setdefault(k, "")
            data.setdefault("Flagged", "false")

            # Defaults
            data["Attribute"] = "Electrical"
            if not (data.get("Asset Group") or "").strip():
                data["Asset Group"] = ASSET_GROUP_DEFAULT

            # Derived Description
            data["Description"] = _desc_from_ubc_or_branch(
                data.get("UBC Asset Tag"),
                data.get("Branch Panel")
            )

            # ---- Photo logic ----
            present_map = {tag: bool(find_image(qr, building, tag)) for tag in ALL_SHOW}
            pass_ok = all(present_map.get(tag, False) for tag in REQUIRED)
            present_all = sum(1 for tag in ALL_SHOW if present_map.get(tag, False))
            fraction = f"{present_all}/3"
            friendly_map = {'-0': 'Asset Plate', '-1': 'UBC Asset Tag', '-2': 'Panel Schedule'}
            missing_list = ", ".join(
                friendly_map[t] for t in ALL_SHOW if not present_map.get(t, False)
            )

            items.append({
                "doc_id": doc_id,
                "qr_code": qr,
                "building": building,
                "asset_type": raw.get("asset_type", ""),
                "Flagged": data.get("Flagged", "false"),
                "Approved": data.get("Approved", ""),
                "Modified": bool(raw.get("modified", False)),
                "Missed Photo": "NO" if pass_ok else "YES",
                "Photos Summary": fraction,
                "Missing List": missing_list,
                **data
            })
        except Exception as e:
            print(f"[WARN] Error loading {filename}: {e}")
    return items


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
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
    keep_blank = [
        "UBC Asset Tag", "Branch Panel", "Ampere", "Supply From", "Volts", "Location",
        "Attribute", "Approved", "Asset Group"
    ]
    for k in keep_blank:
        data.setdefault(k, "")
    data.setdefault("Flagged", "false")

    # Defaults
    data["Attribute"] = "Electrical"
    if not (data.get("Asset Group") or "").strip():
        data["Asset Group"] = ASSET_GROUP_DEFAULT

    data["Description"] = _desc_from_ubc_or_branch(
        data.get("UBC Asset Tag"), data.get("Branch Panel")
    )

    # Thumbnails
    images = {}
    for tag in SEQ_SHOW:
        filename = find_image(qr, building, tag)
        images[tag] = {
            "exists": bool(filename),
            "url": url_for('serve_image', filename=filename) if filename else None
        }

    # Asset Group options (Panels only)
    asset_group_options = _fetch_asset_group_options_panels()

    return render_template(
        "review.html",
        doc_id=doc_id,
        qr_code=qr,
        building=building,
        asset_type=loaded.get("asset_type", ""),
        data=data,
        images=images,
        attribute_options=[],  # kept in case template uses it
        asset_group_options=asset_group_options
    )


@app.route("/review/<doc_id>", methods=["POST"])
def save_review(doc_id):
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

    keep_blank = [
        "UBC Asset Tag", "Branch Panel", "Ampere", "Supply From", "Volts", "Location",
        "Attribute", "Approved", "Asset Group"
    ]
    for k in keep_blank:
        structured.setdefault(k, "")
    structured.setdefault("Flagged", "false")

    # Flagged toggle
    new_flagged = "true" if request.form.get("Flagged") == "on" else "false"
    if structured.get("Flagged", "false") != new_flagged:
        json_data["modified"] = True
    structured["Flagged"] = new_flagged

    # Update editable fields (includes Asset Group)
    skip_fields = {"Flagged", "Description", "Approved"}  # Approved handled via toggle endpoint
    for field in list(structured.keys()):
        if field in skip_fields:
            continue
        form_value = request.form.get(field, "")
        if structured.get(field, "") != form_value:
            json_data["modified"] = True
        structured[field] = form_value

    # Force Attribute to be "Electrical"
    if structured.get("Attribute") != "Electrical":
        json_data["modified"] = True
    structured["Attribute"] = "Electrical"

    # New form fields not present yet
    for field, form_value in request.form.items():
        if field in {"Flagged", "action", "Description", "dashboard_query"}:
            continue
        if field not in structured:
            structured[field] = form_value
            json_data["modified"] = True

    # Recalculate Description
    structured["Description"] = _desc_from_ubc_or_branch(
        structured.get("UBC Asset Tag"), structured.get("Branch Panel")
    )

    # Save JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=4)

    # Sync DB
    try:
        _sync_db_from_structured(qr, building, structured)
    except Exception as e:
        print(f"[WARN] DB sync failed (save_review): {e}")

    # Navigation
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
        return redirect(url_for('review', doc_id=next_doc))
    elif action == "save_prev" and current_index > 0:
        prev_doc = all_files[current_index - 1][:-5]
        return redirect(url_for('review', doc_id=prev_doc))

    dash_q = request.form.get("dashboard_query", "")
    if (dash_q or "").startswith("?"):
        return redirect(url_for("index") + dash_q)
    return redirect(url_for("index"))


@app.route("/toggle_approved/<doc_id>", methods=["POST"])
def toggle_approved(doc_id):
    """
    Toggle Approved in JSON and sync to sdi_dataset_EL.
    DB stores '1' if JSON == 'True', else ''.
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

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        try:
            _sync_db_from_structured(qr, building, structured)
        except Exception as e:
            print(f"[WARN] DB sync failed (toggle_approved): {e}")

        return jsonify({"success": True, "new_value": structured["Approved"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(IMG_DIR, filename)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
