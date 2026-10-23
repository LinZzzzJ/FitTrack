from conftest import profile, register
from fittrack.calculations import nutrients, resting_estimate


def test_resting_and_activity_estimate(client):
    register(client)
    data = profile() | {
        "age": 30,
        "resting_kcal": None,
        "activity_level": "moderate",
        "activity_factor": 1.55,
    }
    saved = client.put("/api/profile", json=data)
    assert saved.status_code == 200, saved.text
    assert saved.json()["estimated_resting_kcal"] == 1699
    assert saved.json()["estimated_maintenance_kcal"] == 2633.5
    summary = client.get("/api/days/2026-10-14").json()
    assert summary["resting_kcal"] == 1699
    assert summary["baseline_kcal"] == 2633.45
    assert resting_estimate(data) == 1699


def test_extended_nutrients_preserve_unknown_values():
    item = {
        "kcal": 100,
        "protein_g": 5,
        "carbs_g": 10,
        "fat_g": 2,
        "fiber_g": 3,
        "sugar_g": None,
        "sodium_mg": 20,
    }
    result = nutrients([item])
    assert result["fiber_g"] == 3
    assert result["sugar_g"] is None
    assert result["sodium_mg"] == 20


def test_text_meal_job_creates_editable_result(client):
    register(client)
    response = client.post(
        "/api/jobs",
        json={
            "kind": "meal",
            "date": "2026-10-22",
            "meal_description": "一碗米饭和一份鸡胸肉",
            "request_key": "text-meal-1",
        },
    )
    assert response.status_code == 202, response.text
    job = response.json()
    for _ in range(100):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in {"done", "failed"}:
            break
    assert job["status"] == "done", job
    assert job["result"]["items"][0]["fiber_g"] is None
    meal = client.post(
        "/api/meals",
        json={
            "date": job["date"],
            "slot": "lunch",
            "title": "",
            "note": "",
            "meal_description": job["request"]["meal_description"],
            "nutrition_mode": "estimate",
            "items": job["result"]["items"],
            "image_id": None,
            "source_job_id": job["id"],
        },
    )
    assert meal.status_code == 201, meal.text
    assert meal.json()["nutrition_mode"] == "estimate"


def test_personal_templates_are_isolated_and_plan_actions_complete(client, app):
    register(client)
    body = {
        "title": "背部基础",
        "category": "back",
        "icon": "back",
        "kind": "strength",
        "duration_minutes": 45,
        "intensity": "moderate",
        "exercises": [{"name": "坐姿划船", "sets": [{"reps": 10, "weight_kg": 30}]}],
        "note": "",
    }
    created = client.post("/api/workout-templates", json=body)
    assert created.status_code == 201, created.text
    template = created.json()
    assert client.get("/api/workout-templates").json() == [template]
    with client.__class__(app) as other:
        register(other, "bob")
        assert other.get("/api/workout-templates").json() == []
        assert other.put(f"/api/workout-templates/{template['id']}", json=body).status_code == 404

    plan = {
        "date": "2026-10-22",
        "title": "引入动作计划",
        "kind": "strength",
        "activity": "strength",
        "duration_minutes": 45,
        "intensity": "moderate",
        "status": "planned",
        "note": "",
        "exercises": body["exercises"],
    }
    saved = client.post("/api/plans", json=plan)
    assert saved.status_code == 201, saved.text
    completed = client.post(f"/api/plans/{saved.json()['id']}/complete")
    assert completed.status_code == 201, completed.text
    day = client.get("/api/days/2026-10-22").json()
    assert day["workouts"][0]["exercises"] == body["exercises"]
    assert client.get("/api/workout-days?start=2026-10-01&end=2026-10-31").json() == [
        "2026-10-22"
    ]


def test_legacy_health_backup_rows_import_without_template_table(client, store):
    from fittrack.control import HEALTH_TABLES
    from fittrack.storage_ops import import_rows

    uid = register(client)["id"]
    legacy_tables = {table: [] for table in HEALTH_TABLES if table != "workout_templates"}
    import_rows(store, uid, legacy_tables)
    assert store.templates(uid) == []


def test_precise_meal_survives_health_backup_validation_and_import(client, store):
    from fittrack.control import HEALTH_TABLES
    from fittrack.storage_ops import import_rows, validate_rows

    uid = register(client)["id"]
    saved = client.post(
        "/api/meals",
        json={
            "date": "2026-10-22",
            "slot": "dinner",
            "title": "鸡肉饭",
            "meal_description": "鸡肉饭一份",
            "nutrition_mode": "precise",
            "items": [{"name": "鸡肉饭一份", "protein_g": 30, "carbs_g": 50, "fat_g": 12}],
        },
    )
    assert saved.status_code == 201, saved.text
    tables = {
        table: store.rows(f"SELECT * FROM {table} WHERE user_id=?", (uid,))
        for table in HEALTH_TABLES
    }
    validate_rows(tables)
    import_rows(store, uid, tables)
    restored = store.entries(uid, "meal", "2026-10-22", "2026-10-22")[0]
    assert restored["nutrition_mode"] == "precise"
    assert restored["meal_description"] == "鸡肉饭一份"
    assert restored["items"][0]["kcal"] == 428


def test_resting_estimate_requires_age_when_no_manual_value(client):
    register(client)
    payload = profile() | {"age": None, "resting_kcal": None}
    assert client.put("/api/profile", json=payload).status_code == 422


def test_precise_meal_uses_server_calculated_macro_energy(client):
    register(client)
    response = client.post(
        "/api/meals",
        json={
            "date": "2026-10-22",
            "slot": "lunch",
            "title": "板烧鸡腿堡",
            "meal_description": "麦当劳板烧鸡腿堡 1 个，去除酱料",
            "nutrition_mode": "precise",
            "items": [
                {
                    "name": "板烧鸡腿堡",
                    "consumed_part": "整餐精确录入",
                    "estimated_edible_grams": None,
                    "kcal": 19999,
                    "protein_g": 30,
                    "carbs_g": 40,
                    "fat_g": 10,
                    "fiber_g": 5,
                    "sugar_g": None,
                    "sodium_mg": 700,
                }
            ],
            "image_id": None,
            "source_job_id": None,
        },
    )
    assert response.status_code == 201, response.text
    saved_item = response.json()["items"][0]
    assert saved_item["kcal"] == 370
    assert saved_item["estimated_edible_grams"] is None
    assert response.json()["nutrition_mode"] == "precise"
    assert response.json()["source_job_id"] is None
    assert response.json()["assumptions"] == []

    edited = client.put(
        f"/api/meals/{response.json()['id']}",
        json={
            "date": "2026-10-22",
            "slot": "lunch",
            "title": "板烧鸡腿堡",
            "meal_description": "麦当劳板烧鸡腿堡 1 个，去除酱料",
            "nutrition_mode": "precise",
            "items": [
                {
                    "name": "板烧鸡腿堡",
                    "estimated_edible_grams": None,
                    "kcal": 1,
                    "protein_g": 20,
                    "carbs_g": 30,
                    "fat_g": 5,
                }
            ],
            "image_id": None,
            "source_job_id": None,
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["items"][0]["kcal"] == 245


def test_precise_meal_requires_description_and_one_macro_summary(client):
    register(client)
    base = {
        "date": "2026-10-22",
        "slot": "lunch",
        "title": "精确餐食",
        "nutrition_mode": "precise",
        "image_id": None,
        "source_job_id": None,
    }
    item = {
        "name": "精确餐食",
        "protein_g": 10,
        "carbs_g": 20,
        "fat_g": 5,
    }
    no_description = client.post("/api/meals", json=base | {"items": [item]})
    assert no_description.status_code == 422
    multiple_items = client.post(
        "/api/meals",
        json=base
        | {
            "meal_description": "测试精确录入餐食",
            "items": [item, item | {"name": "第二项"}],
        },
    )
    assert multiple_items.status_code == 422


def test_precise_meal_rejects_energy_over_model_limit(client):
    register(client)
    response = client.post(
        "/api/meals",
        json={
            "date": "2026-10-22",
            "slot": "dinner",
            "meal_description": "非常大份精确录入餐食",
            "nutrition_mode": "precise",
            "items": [
                {
                    "name": "整餐",
                    "protein_g": 2000,
                    "carbs_g": 5000,
                    "fat_g": 2000,
                }
            ],
        },
    )
    assert response.status_code == 422


def test_precise_meal_rejects_macro_outside_item_field_limit(client):
    register(client)
    response = client.post(
        "/api/meals",
        json={
            "date": "2026-10-22",
            "meal_description": "超大数值测试餐",
            "nutrition_mode": "precise",
            "items": [
                {
                    "name": "整餐",
                    "protein_g": 1e300,
                    "carbs_g": 0,
                    "fat_g": 0,
                }
            ],
        },
    )
    assert response.status_code == 422


def test_label_snapshot_cannot_use_precise_mode(client):
    register(client)
    label = {
        "label": {
            "name": "标签商品",
            "basis_kind": "per_100g",
            "basis_grams": 100,
            "energy_value": 100,
            "energy_unit": "kcal",
            "protein_g": 10,
            "carbs_g": 10,
            "fat_g": 2,
            "assumptions": [],
        },
        "portion": {"mode": "grams", "grams": 50},
    }
    response = client.post(
        "/api/meals",
        json={
            "date": "2026-10-22",
            "meal_description": "标签商品 50 克",
            "nutrition_mode": "precise",
            "nutrition_label": label,
            "items": [
                {"name": "标签商品", "kcal": 50, "protein_g": 5, "carbs_g": 5, "fat_g": 1}
            ],
        },
    )
    assert response.status_code == 422


def test_estimated_meal_still_requires_each_item_weight(client):
    register(client)
    response = client.post(
        "/api/meals",
        json={
            "date": "2026-10-22",
            "nutrition_mode": "estimate",
            "meal_description": "估算餐食重量缺失测试",
            "items": [
                {
                    "name": "米饭",
                    "kcal": 200,
                    "protein_g": 4,
                    "carbs_g": 44,
                    "fat_g": 0.5,
                }
            ],
        },
    )
    assert response.status_code == 422
