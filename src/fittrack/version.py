"""Loaded backend identity, independent of disk-served frontend assets."""

import hashlib
import json
from pathlib import Path

from fittrack.distribution import FROZEN

APP_VERSION = "0.4.0"
API_REVISION = 5
CAPABILITIES = [
    "cardio_estimate",
    "weekly_review",
    "diet_history",
    "nutrition_label",
    "meal_job_delete",
    "text_meal_estimate",
    "expanded_nutrition",
    "workout_templates",
    "training_import",
    "activity_estimates",
    "meal_entry_modes",
    "precise_meal_energy",
    "exercise_catalog",
    "mobile_pairing",
    "mobile_sync_v1",
]


def source_fingerprint():
    if FROZEN:
        return hashlib.sha256((Path(__file__).parent / "build-info.json").read_bytes()).hexdigest()
    digest = hashlib.sha256()
    base = Path(__file__).parent
    for path in sorted(base.rglob("*.py")):
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class BuildInfo:
    def __init__(self):
        self.loaded = source_fingerprint()

    def public(self):
        try:
            changed = self.loaded != source_fingerprint()
        except OSError:
            changed = True
        return {
            "version": APP_VERSION,
            "api_revision": API_REVISION,
            "capabilities": CAPABILITIES,
            "backend_build": self.loaded,
            "restart_required": changed,
            "distribution": "portable" if FROZEN else "source",
            "build_id": json.loads(
                (Path(__file__).parent / "build-info.json").read_text(encoding="utf-8")
            )["build_id"]
            if FROZEN
            else self.loaded[:16],
        }
