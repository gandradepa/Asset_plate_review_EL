import os
import json
import re
import sqlite3
from functools import lru_cache
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify

app = Flask(
    __name__,
    template_folder=r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\Asset_plate_review_ME\review_asset_templates",
    static_folder=r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\Asset_plate_review_ME\review_asset_templates\static"
)

# --- Paths ---
JSON_DIR = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test\Output_jason_api"
IMG_DIR  = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test"

# --- SQLite DB (for dropdown options) ---
DB_PATH = r"S:\MaintOpsPlan\AssetMgt\Asset Management Process\Database\8. New Assets\Git_control\API Picture Test\QR_codes.db"

# Adjust these if your schema differs:
ASSET_GROUP_TABLE = "Asset_Group"
ASSET_GROUP_COL   = "name"   # e.g., name / Asset_Group / GroupName

ATTRIBUTE_TABLE   = "Attribute"
ATTRIBUTE_COL     = "Code"   # per your request

VALID_IMAGE_EXTS = ['.jpg', '.JPG', '.jpeg', '.JPEG', '.png', '.PNG']

# Missed Photo check: any missing among -0, -1, -2 => YES
SEQ_CHECK = ['-0', '-1', '-2']
# Review can show -3 if present
SEQ_SHOW  = ['-0', '-1', '-2', '-3']

# JSON filename pattern: "<QR>_ME_<Building>.json"
JSON_NAME_RE = re.compile(r"^(\d+)_([A-Za-z]+)_(\d+(?:-\d+)?)\.json$")


def find_image(qr: str, building: str, seq_tag: str):
    """Find image by pattern: '<QR> <Building> ME - <seq>.<ext>'."""
    seq = seq_tag.replace('-', '').strip()
    base = f"{qr} {building} ME - {seq}"
    for ext in VALID_IMAGE_EXTS:
        candidate = os.path.join(IMG_DIR, base + ext)
        if os.path.exists(candidate):
            return os.path.basename(candidate)
    return None


@lru_cache(maxsize=1)
def _connectable():
    """Check DB path once (cached)."""
    return os.path.exists(DB_PATH)


def _fetch_column_values(table: str, col: str):
    """Return sorted unique non-empty strings for dropdowns."""
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


def get_asset_group_options():
    return _fetch_column_values(ASSET_GROUP_TABLE, ASSET_GROUP_COL)


def get_attribute_options():
    return _fetch_column_values(ATTRIBUTE_TABLE, ATTRIBUTE_COL)


def _compute_description(asset_group: str, ubc_tag: str) -> str:
    ag = (asset_group or "").strip()
    ubc = (ubc_tag or "").strip()
    if ag and ubc:
        return f"{ag} - {ubc}"
    return ag or ubc


def load_json_items():
    items = []
    for filename in os.listdir(JSON_DIR):
        if not filename.endswith(".json") or filename.endswith("_raw_ocr.json"):
            continue

        m = JSON_NAME_RE.match(filename)
        if not m:
            continue

        qr, asset_type_mid, building = m.groups()
        doc_id = filename[:-5]  # strip ".json"

        try:
            with open(os.path.join(JSON_DIR, filename), 'r', encoding='utf-8') as f:
                raw = json.load(f)

            data = raw.get("structured_data") or {}
            if not isinstance(data, dict):
                print(f"⚠️ Skipped {filename}: 'structured_data' is not a dict")
                continue

            # Ensure keys exist to keep them visible/editable
            data.setdefault("Manufacturer", "")
            data.setdefault("Model", "")
            data.setdefault("Serial Number", "")
            data.setdefault("Year", "")
            data.setdefault("UBC Asset Tag", "")
            data.setdefault("Technical Safety BC", "")
            data.setdefault("Asset Group", "")
            data.setdefault("Attribute", "")
            data.setdefault("Flagged", "false")
            data.setdefault("Approved", "")  # NEW: default blank = False

            # Derived: Description = "Asset Group - UBC Tag"
            data["Description"] = _compute_description(
                data.get("Asset Group"),
                data.get("UBC Asset Tag")
            )

            # Compute missing list (-0, -1, -2)
            missing_tags = [tag for tag in SEQ_CHECK if not find_image(qr, building, tag)]
            missing_photo = len(missing_tags) > 0
            friendly_map = {'-0': 'Asset Plate', '-1': 'UBC Tag', '-2': 'Main Picture'}
            missing_friendly = ", ".join(friendly_map.get(tag, tag) for tag in missing_tags)

            items.append({
                "doc_id": doc_id,
                "qr_code": qr,
                "building": building,
                "asset_type": raw.get("asset_type", ""),
                "Flagged": data.get("Flagged", "false"),
                "Approved": data.get("Approved", ""),  # include in dashboard data
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

    qr, asset_type_mid, building = m.groups()
    with open(json_path, 'r', encoding='utf-8') as f:
        loaded = json.load(f)

    data = loaded.get("structured_data", {}) or {}
    data.setdefault("Asset Group", "")
    data.setdefault("Attribute", "")
    data.setdefault("UBC Tag", "")
    data.setdefault("Approved", "")  # keep approved in data set
    data["Description"] = _compute_description(data.get("Asset Group"), data.get("UBC Tag"))

    # Build image map
    images = {}
    for tag in SEQ_SHOW:
        filename = find_image(qr, building, tag)
        if filename:
            images[tag] = {"exists": True, "url": url_for('serve_image', filename=filename)}
        else:
            images[tag] = {"exists": False, "url": None}

    # Dropdown options from DB
    asset_group_options = get_asset_group_options()
    attribute_options   = get_attribute_options()

    return render_template(
        "review.html",
        doc_id=doc_id,
        qr_code=qr,
        building=building,
        asset_type=loaded.get("asset_type", ""),
        data=data,
        images=images,
        asset_group_options=asset_group_options,
        attribute_options=attribute_options
    )


@app.route("/review/<doc_id>", methods=["POST"])
def save_review(doc_id):
    json_path = os.path.join(JSON_DIR, f"{doc_id}.json")
    if not os.path.exists(json_path):
        return "Not found", 404

    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    structured = json_data.get("structured_data", {})
    if not isinstance(structured, dict):
        structured = {}
        json_data["structured_data"] = structured

    # Ensure critical keys exist
    structured.setdefault("Asset Group", "")
    structured.setdefault("Attribute", "")
    structured.setdefault("UBC Asset Tag", "")
    structured.setdefault("Approved", "")  # ensure exists, but not toggled here
    structured.setdefault("Flagged", "false")

    # Update Flagged
    new_flagged = "true" if request.form.get("Flagged") == "on" else "false"
    if structured.get("Flagged", "false") != new_flagged:
        json_data["modified"] = True
    structured["Flagged"] = new_flagged

    # Update known fields (skip derived Description and Approved)
    for field in list(structured.keys()):
        if field in ("Flagged", "Description", "Approved"):
            continue
        form_value = request.form.get(field, "")
        if structured.get(field, "") != form_value:
            json_data["modified"] = True
        structured[field] = form_value

    # Capture any brand-new fields (future-proof)
    for field, form_value in request.form.items():
        if field in ("Flagged", "action", "Description", "dashboard_query"):
            continue
        if field not in structured:
            structured[field] = form_value
            json_data["modified"] = True

    # Recompute derived Description
    structured["Description"] = _compute_description(
        structured.get("Asset Group"),
        structured.get("UBC Tag")
    )

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=4)

    # Next/Prev navigation stays within review context
    all_files = sorted(
        f for f in os.listdir(JSON_DIR)
        if f.endswith(".json") and not f.endswith("_raw_ocr.json") and JSON_NAME_RE.match(f)
    )
    current_name = f"{doc_id}.json"
    try:
        current_index = all_files.index(current_name)
    except ValueError:
        dash_q = request.form.get("dashboard_query", "")
        if dash_q.startswith("?"):
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
    if dash_q.startswith("?"):
        return redirect(url_for("index") + dash_q)

    return redirect(url_for("index"))


@app.route("/toggle_approved/<doc_id>", methods=["POST"])
def toggle_approved(doc_id):
    """Toggle Approved between '' (False) and 'True' (True) and persist to file."""
    json_path = os.path.join(JSON_DIR, f"{doc_id}.json")
    if not os.path.exists(json_path):
        return jsonify({"success": False, "error": "Not found"}), 404

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)

        structured = json_data.get("structured_data", {})
        if not isinstance(structured, dict):
            structured = {}
            json_data["structured_data"] = structured

        current = structured.get("Approved", "")
        structured["Approved"] = "True" if current == "" else ""
        json_data["structured_data"] = structured

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)

        return jsonify({"success": True, "new_value": structured["Approved"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(IMG_DIR, filename)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
