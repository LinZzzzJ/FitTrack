import importlib.util
import json
from pathlib import Path


def test_mobile_contracts_match_current_python_models_and_catalogue():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "mobile_contract_export", root / "scripts/export_mobile_contracts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (
        json.loads((root / "web/src/lib/mobile-contracts.json").read_text(encoding="utf-8"))
        == module.export()
    )


def test_precise_health_restore_recalculates_untrusted_kcal():
    from fittrack.control import HEALTH_TABLES
    from fittrack.storage_ops import validate_rows

    tables = {name: [] for name in HEALTH_TABLES}
    tables["entries"] = [
        {
            "id": "a" * 24,
            "user_id": "b" * 24,
            "kind": "meal",
            "date": "2026-10-20",
            "source_job_id": None,
            "plan_id": None,
            "created_at": 1,
            "data": json.dumps(
                {
                    "date": "2026-10-20",
                    "nutrition_mode": "precise",
                    "meal_description": "synthetic",
                    "items": [
                        {
                            "name": "synthetic",
                            "kcal": 999,
                            "protein_g": 10,
                            "carbs_g": 20,
                            "fat_g": 5,
                        }
                    ],
                }
            ),
        }
    ]
    validate_rows(tables)
    assert json.loads(tables["entries"][0]["data"])["items"][0]["kcal"] == 165
