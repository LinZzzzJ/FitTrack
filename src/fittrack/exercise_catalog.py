"""Built-in exercise catalogue shared by the web and mobile clients.

The catalogue is deliberately kept outside health records and backup rows.  This
keeps the v1/v2 health archive contract readable by older PC releases while a
client can still resolve an exercise name to an illustrated movement.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExerciseDefinition:
    id: str
    name: str
    body_part: str
    media_ref: str
    cue: str


_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "back": (
        ("lat-pulldown", "高位下拉"),
        ("seated-row", "坐姿划船"),
        ("one-arm-dumbbell-row", "单臂哑铃划船"),
        ("barbell-row", "杠铃划船"),
        ("assisted-pull-up", "辅助引体向上"),
        ("straight-arm-pulldown", "直臂下压"),
    ),
    "chest": (
        ("barbell-bench-press", "杠铃卧推"),
        ("incline-dumbbell-press", "上斜哑铃卧推"),
        ("push-up", "俯卧撑"),
        ("cable-fly", "绳索夹胸"),
        ("chest-press", "坐姿推胸"),
        ("dumbbell-fly", "哑铃飞鸟"),
    ),
    "shoulders": (
        ("seated-overhead-press", "坐姿推举"),
        ("dumbbell-lateral-raise", "哑铃侧平举"),
        ("rear-delt-fly", "反向飞鸟"),
        ("front-raise", "前平举"),
        ("arnold-press", "阿诺德推举"),
        ("face-pull", "面拉"),
    ),
    "arms": (
        ("dumbbell-curl", "哑铃弯举"),
        ("hammer-curl", "锤式弯举"),
        ("cable-pushdown", "绳索下压"),
        ("overhead-triceps-extension", "过顶臂屈伸"),
        ("preacher-curl", "牧师凳弯举"),
        ("close-grip-push-up", "窄距俯卧撑"),
    ),
    "legs": (
        ("back-squat", "深蹲"),
        ("romanian-deadlift", "罗马尼亚硬拉"),
        ("leg-press", "腿举"),
        ("walking-lunge", "行走弓步"),
        ("leg-extension", "腿屈伸"),
        ("leg-curl", "腿弯举"),
    ),
    "core": (
        ("plank", "平板支撑"),
        ("dead-bug", "死虫"),
        ("cable-crunch", "绳索卷腹"),
        ("hanging-knee-raise", "悬垂举膝"),
        ("bicycle-crunch", "自行车卷腹"),
        ("pallof-press", "帕洛夫抗旋"),
    ),
    "full_body": (
        ("kettlebell-swing", "壶铃摆动"),
        ("burpee", "波比跳"),
        ("thruster", "深蹲推举"),
        ("mountain-climber", "登山跑"),
        ("clean-and-press", "高翻推举"),
        ("farmer-carry", "农夫走"),
    ),
    "cardio": (
        ("treadmill-walk", "跑步机快走"),
        ("treadmill-run", "跑步机跑步"),
        ("stationary-bike", "固定自行车"),
        ("elliptical", "椭圆机"),
        ("rowing-machine", "划船机"),
        ("jump-rope", "跳绳"),
    ),
}


def _definition(group: str, ident: str, name: str) -> ExerciseDefinition:
    return ExerciseDefinition(
        id=ident,
        name=name,
        body_part=group,
        # The client may ship a licensed animation at this stable path.  No
        # media is fetched from the network by resolving a catalogue entry.
        media_ref=f"exercise-media/{ident}.webp",
        cue="动作过程中保持可控速度，按个人能力调整重量。",
    )


CATALOG: tuple[ExerciseDefinition, ...] = tuple(
    _definition(group, ident, name)
    for group, values in _GROUPS.items()
    for ident, name in values
)
BY_ID = {item.id: item for item in CATALOG}
BY_NAME = {item.name: item for item in CATALOG}


def exercise_catalog() -> list[dict[str, str]]:
    """Return JSON-safe catalogue data without exposing filesystem paths."""

    return [
        {
            "id": item.id,
            "name": item.name,
            "body_part": item.body_part,
            "media_ref": item.media_ref,
            "cue": item.cue,
        }
        for item in CATALOG
    ]
