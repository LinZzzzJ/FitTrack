"""Label arithmetic uses confirmed values, never guesses missing nutrients."""

from fittrack.models import FoodItem, NutritionLabel


def label_food(values):
    snapshot = NutritionLabel.model_validate(values)
    label, portion = snapshot.label, snapshot.portion
    missing = []
    for field, name in (
        ("name", "商品名称"),
        ("basis_kind", "标签基准"),
        ("energy_value", "标签能量"),
        ("energy_unit", "能量单位"),
        ("protein_g", "蛋白质"),
        ("carbs_g", "碳水"),
        ("fat_g", "脂肪"),
    ):
        if getattr(label, field) is None or getattr(label, field) == "":
            missing.append(name)
    basis = 100 if label.basis_kind == "per_100g" else label.basis_grams
    if basis is None:
        missing.append("每份或整包的基准克数")
    if label.basis_kind == "per_100g" and label.basis_grams not in {None, 100}:
        raise ValueError("每100克标签的基准重量必须为100克")
    if portion.mode == "grams":
        grams = portion.grams
        if grams is None:
            missing.append("实际食用克数")
        consumed = "按实际食用克数"
    else:
        if portion.pack_grams is None:
            missing.append("每袋重量")
        if portion.packs is None:
            missing.append("实际食用袋数")
        grams = (
            portion.pack_grams * portion.packs
            if portion.pack_grams is not None and portion.packs is not None
            else None
        )
        consumed = f"每袋{portion.pack_grams:g}g × {portion.packs:g}袋" if grams is not None else ""
    if missing:
        raise ValueError("请补充或确认：" + "、".join(missing))
    factor = grams / basis
    energy = label.energy_value / 4.184 if label.energy_unit == "kJ" else label.energy_value
    return FoodItem.model_validate(
        {
            "name": label.name,
            "consumed_part": consumed,
            "estimated_edible_grams": round(grams, 4),
            "kcal": round(energy * factor, 2),
            "protein_g": round(label.protein_g * factor, 2),
            "carbs_g": round(label.carbs_g * factor, 2),
            "fat_g": round(label.fat_g * factor, 2),
        }
    ).model_dump()
