from __future__ import annotations

"""Auditable race-development interaction features for BOAT EV.

These features encode race-shape hypotheses without silently changing production
probabilities. Historical/out-of-sample validation must estimate effect sizes
before coefficients are adopted.
"""


def _num(b, key):
    v = (b or {}).get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def build_interaction_features(boats: list[dict]) -> dict:
    """Build interaction features from six boats ordered by actual exhibition course.

    Optional keys per boat:
      boat, course, avg_st, exhibition_st, exhibition_time, motor_rate,
      local_win_rate, national_win_rate, class_rank, is_dash

    Lower ST/exhibition_time is better. Missing values stay None.
    """
    by_course = {
        int(b.get("course", b.get("boat"))): b
        for b in boats
        if b.get("course", b.get("boat")) is not None
    }
    dash_courses = sorted(c for c, b in by_course.items() if bool(b.get("is_dash")))
    kado_course = dash_courses[0] if dash_courses else None

    rows = []
    for c in range(1, 7):
        b = by_course.get(c, {})
        inner = by_course.get(c - 1) if c > 1 else None
        outer = by_course.get(c + 1) if c < 6 else None
        two_outer = by_course.get(c + 2) if c < 5 else None

        avg = _num(b, "avg_st")
        ex = _num(b, "exhibition_st")
        inner_avg = _num(inner, "avg_st")
        inner_ex = _num(inner, "exhibition_st")

        rows.append({
            "boat": b.get("boat", c),
            "course": c,
            "is_dash": bool(b.get("is_dash")),
            "is_kado": c == kado_course,
            "is_3kado": c == 3 and kado_course == 3,
            "is_4kado": c == 4 and kado_course == 4,
            "is_one_outside_kado": kado_course is not None and c == kado_course + 1,
            "is_two_outside_kado": kado_course is not None and c == kado_course + 2,
            "avg_st_adv_vs_inner": (inner_avg - avg) if avg is not None and inner_avg is not None else None,
            "exhibition_st_adv_vs_inner": (inner_ex - ex) if ex is not None and inner_ex is not None else None,
            "outer_boat": (outer or {}).get("boat") if outer else None,
            "two_outer_boat": (two_outer or {}).get("boat") if two_outer else None,
            "exhibition_time": _num(b, "exhibition_time"),
            "motor_rate": _num(b, "motor_rate"),
            "local_win_rate": _num(b, "local_win_rate"),
            "national_win_rate": _num(b, "national_win_rate"),
            "class_rank": b.get("class_rank"),
        })

    kado = by_course.get(kado_course) if kado_course else None
    one_out = by_course.get(kado_course + 1) if kado_course and kado_course < 6 else None
    two_out = by_course.get(kado_course + 2) if kado_course and kado_course < 5 else None

    pair = None
    if kado and one_out:
        pair = {
            "attacker_boat": kado.get("boat"),
            "beneficiary_boat": one_out.get("boat"),
            "attacker_course": kado_course,
            "beneficiary_course": kado_course + 1,
            "attacker_avg_st": _num(kado, "avg_st"),
            "attacker_exhibition_st": _num(kado, "exhibition_st"),
            "attacker_exhibition_time": _num(kado, "exhibition_time"),
            "attacker_motor_rate": _num(kado, "motor_rate"),
            "beneficiary_avg_st": _num(one_out, "avg_st"),
            "beneficiary_exhibition_st": _num(one_out, "exhibition_st"),
            "beneficiary_exhibition_time": _num(one_out, "exhibition_time"),
            "beneficiary_motor_rate": _num(one_out, "motor_rate"),
            "beneficiary_local_win_rate": _num(one_out, "local_win_rate"),
            "beneficiary_national_win_rate": _num(one_out, "national_win_rate"),
            "beneficiary_class_rank": one_out.get("class_rank"),
        }

    second_out_pair = None
    if kado and two_out:
        second_out_pair = {
            "attacker_boat": kado.get("boat"),
            "beneficiary_boat": two_out.get("boat"),
            "attacker_course": kado_course,
            "beneficiary_course": kado_course + 2,
            "reason": "venue/race-shape dependent second-outside flow; validate separately",
        }

    return {
        "kado_course": kado_course,
        "is_3kado": kado_course == 3,
        "is_4kado": kado_course == 4,
        "kado_outside_pair": pair,
        "kado_two_outside_pair": second_out_pair,
        "boats": rows,
        "status": "measurement_only",
        "note": "No production probability adjustment until historical validation estimates effect sizes.",
    }


def interaction_hypotheses() -> list[dict]:
    """Pre-registered hypotheses; evaluate without hindsight leakage."""
    return [
        {"id": "KADO_ATTACK", "question": "Does a strong-starting kado boat increase its own 1st/2nd-place rate?"},
        {"id": "OUTSIDE_KADO", "question": "Conditional on kado attack strength, does the immediately outside boat gain 1st/2nd/3rd probability?"},
        {"id": "SECOND_OUTSIDE_KADO", "question": "Under which venues/entry shapes does the boat two outside the kado gain finishing probability?"},
        {"id": "THREE_KADO", "question": "Does 3-kado change the distribution for courses 3/4/5 versus ordinary 3-course slow entry?"},
        {"id": "FOUR_KADO", "question": "How does 4-kado alter probabilities for courses 4/5/6 versus ordinary 4-course entry?"},
        {"id": "ABILITY_GATE", "question": "Is outside-flow benefit conditional on racer/motor/local ability being sufficient?"},
        {"id": "ST_CHAIN", "question": "Does average/exhibition ST advantage versus the inner boat propagate value to outside boats?"},
        {"id": "EXHIBITION_GATE", "question": "Does exhibition ST/time strengthen or weaken the historical kado/outside effect?"},
        {"id": "VENUE_INTERACTION", "question": "Does kado/outside effect materially differ by venue and water-course characteristics?"},
    ]
