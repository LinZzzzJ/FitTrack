from fittrack.exercise_catalog import CATALOG, BY_ID, BY_NAME


def test_catalog_has_six_safe_entries_per_body_part():
    groups = {}
    for item in CATALOG:
        groups.setdefault(item.body_part, []).append(item)
        assert item.id in BY_ID
        assert BY_NAME[item.name] is item
        assert item.media_ref.startswith("exercise-media/")
        assert not item.media_ref.startswith(("/", "http:", "https:"))
    assert set(groups) == {
        "back",
        "chest",
        "shoulders",
        "arms",
        "legs",
        "core",
        "full_body",
        "cardio",
    }
    assert all(len(items) == 6 for items in groups.values())


def test_catalog_json_is_stable_and_does_not_expose_paths():
    from fittrack.exercise_catalog import exercise_catalog

    rows = exercise_catalog()
    assert len(rows) == len(CATALOG)
    assert all(set(row) == {"id", "name", "body_part", "media_ref", "cue"} for row in rows)
    assert all("\\" not in row["media_ref"] for row in rows)
