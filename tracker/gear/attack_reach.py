"""Reviewed ordinary attack reach, independent of obstacle or NPC behaviour.

https://oldschool.runescape.wiki/w/Attack_range
Reviewed ranged profiles (bows, crossbows and thrown weapons) have at least
two tiles of reach. Salamanders' one-tile diagonal attacks are excluded.
"""

from typing import Any

from tracker.gear.halberds import FORMS
from tracker.gear.models import EquipmentDefinition

MODEL_VERSION = "safe-spotting-reach-v1"
SALAMANDERS = frozenset({10146, 10147, 10148, 28834, 10149})

# Exact pinned catalog profiles; new forms require an explicit reach review.
REVIEWED_RANGED_IDS = frozenset(
    {
        732,
        767,
        800,
        801,
        802,
        803,
        804,
        805,
        806,
        807,
        808,
        809,
        810,
        811,
        812,
        813,
        814,
        815,
        816,
        817,
        837,
        839,
        841,
        843,
        845,
        847,
        849,
        851,
        853,
        855,
        857,
        859,
        861,
        863,
        864,
        865,
        866,
        867,
        868,
        869,
        870,
        871,
        872,
        873,
        874,
        875,
        876,
        2883,
        3093,
        3094,
        4212,
        4214,
        4215,
        4216,
        4217,
        4218,
        4219,
        4220,
        4221,
        4222,
        4223,
        4236,
        4734,
        4827,
        4934,
        4935,
        4936,
        4937,
        4938,
        5628,
        5629,
        5630,
        5631,
        5632,
        5633,
        5634,
        5635,
        5636,
        5637,
        5638,
        5639,
        5640,
        5641,
        5654,
        5655,
        5656,
        5657,
        5658,
        5659,
        5660,
        5661,
        5662,
        5663,
        5664,
        5665,
        5666,
        5667,
        6522,
        6724,
        7170,
        8880,
        9174,
        9176,
        9177,
        9179,
        9181,
        9183,
        9185,
        9705,
        10156,
        10280,
        10282,
        10284,
        11230,
        11231,
        11233,
        11234,
        11235,
        11708,
        11748,
        11749,
        11750,
        11751,
        11752,
        11753,
        11754,
        11755,
        11756,
        11757,
        11758,
        11785,
        12424,
        12765,
        12766,
        12767,
        12768,
        12788,
        12924,
        12926,
        19478,
        19481,
        20849,
        20997,
        21012,
        21902,
        22333,
        22547,
        22550,
        22634,
        22636,
        22804,
        22806,
        22808,
        22810,
        23357,
        23855,
        23856,
        23857,
        23901,
        23902,
        23903,
        23983,
        25849,
        25851,
        25855,
        25857,
        25862,
        25865,
        25867,
        25884,
        25886,
        25888,
        25890,
        25892,
        25894,
        25896,
        25916,
        25918,
        26374,
        26486,
        26712,
        27610,
        27612,
        27652,
        27655,
        27853,
        27912,
        27916,
        28053,
        28687,
        28688,
        28773,
        28794,
        28869,
        28919,
        28922,
        29000,
        29305,
        29591,
        29611,
        30373,
        30374,
        30434,
        30436,
        31575,
        31577,
        31579,
        31581,
        31583,
        31585,
        33021,
        33245,
        33251,
        33716,
        33790,
        33800,
    }
)


def safe_spotting_problem(weapon: EquipmentDefinition | None, role: Any) -> str | None:
    if not getattr(role, "safe_spotting", False):
        return None
    style = role.style
    supported = False
    if style in {"stab", "slash", "crush"}:
        supported = weapon is not None and weapon.id in FORMS
    elif style == "ranged":
        supported = bool(
            weapon
            and weapon.id in REVIEWED_RANGED_IDS
            and weapon.id not in SALAMANDERS
            and any(p[0] == "ranged" for p in weapon.attack_profiles)
        )
    elif style == "magic":
        # Casting uses the spell's reach, not the wielded staff's melee reach.
        from tracker.gear.combat import SPELLS
        from tracker.gear.powered import supports_powered

        supported = (
            bool(weapon and supports_powered(weapon))
            if getattr(role, "powered_attack", None)
            else role.spell in SPELLS
        )
    if supported:
        return None
    name = weapon.name if weapon else "Unarmed attacks"
    return (
        f"Safe spotting requires reviewed attack reach of at least two tiles; "
        f"{name} cannot satisfy the selected {style} attack."
    )


def policy_context(request: Any) -> dict[str, Any]:
    from tracker.gear.halberds import MODEL_VERSION as HALBERD_MODEL_VERSION
    from tracker.gear.status_damage import MODEL_VERSION as STATUS_MODEL_VERSION

    return {
        "safe_spotting_model_version": MODEL_VERSION,
        "halberd_model_version": HALBERD_MODEL_VERSION,
        "status_damage_model_version": STATUS_MODEL_VERSION,
        "safe_spotting": {r.id: r.safe_spotting for r in request.roles},
        "fight_duration_seconds": {r.id: r.fight_duration_seconds for r in request.roles},
        "status_target_state": "independent-clean-target-continuous-attacks",
        "status_susceptibility": {
            r.id: {
                "poison": getattr(r.target, "poison_susceptibility", "unknown"),
                "venom": getattr(r.target, "venom_susceptibility", "unknown"),
            }
            for r in request.roles
        },
    }
