"""Load exact worn and inventory weights without modifying the reviewed combat catalog."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path


def load_weights(
    root: Path, manifest: dict[str, object]
) -> tuple[dict[int, dict[str, int | None]], bytes]:
    path = root / "weights.json"
    if not path.exists():
        if "weights_sha256" in manifest:
            raise ValueError("Catalog manifest references missing equipment weights.json")
        return {}, b""
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != manifest.get("weights_sha256"):
        raise ValueError("Equipment weights checksum mismatch")
    data = json.loads(payload)
    if data["schema_version"] != 1:
        raise ValueError("Unsupported equipment weights schema")
    if data["provenance"]["capture_sha256"] != manifest.get("capture_sha256"):
        raise ValueError("Equipment weights belong to a different physical capture")
    forms = data["inventory_forms"]
    bag_grams = {form["id"]: form["grams"] for form in forms.values()}
    rows = {}
    for key, worn in data["worn_grams"].items():
        item_id = int(key)
        form = forms.get(key)
        bag_id = form["id"] if form else item_id
        rows[item_id] = {
            "worn_weight_grams": worn,
            "inventory_weight_grams": bag_grams.get(bag_id, worn),
            "inventory_form_id": bag_id if form else None,
        }
    return rows, payload
