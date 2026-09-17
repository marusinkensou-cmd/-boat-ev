from __future__ import annotations

"""Auditable interaction features for BOAT EV.

This module intentionally DOES NOT alter production probabilities yet.
It converts race-shape ideas into measurable features so historical data can
estimate their real effect before any coefficient is adopted.
"""


def build_interaction_features(boats: list[dict]) -> dict:
    """Return interaction features from six boats ordered by actual course.

    Expected optional keys per boat:
      boat, course, avg_st, exhibition_st, exhibition_time, motor_rate,
      local_win_rate, national_win_rate, class_rank, is_dash

    Lower ST/time is better. Missing values remain None; no invented values.
    """
    by_course = {int(b.get("course", b.get("boat"))): b for b in boats if b.get("course", b.get("boat")) is not None}
    dash_courses = sorted(c for c,b in by_course.items() if bool(b.get("is_dash")))
    kado_course = dash_courses[0] if dash_courses else None

    def f(b, key):
        v = (b or {}).get(key)
        try: return float(v) if v is not None else None
        except (TypeError, ValueError): return None

    rows=[]
    for c in range(1,7):
        b=by_course.get(c, {})
        inner=by_course.get(c-1) if c>1 else None
        outer=by_course.get(c+1) if c<6 else None
        avg=f(b,"avg_st"); ex=f(b,"exhibition_st")
        inner_avg=f(inner,"avg_st"); inner_ex=f(inner,"exhibition_st")
        rows.append({
            "boat": b.get("boat",c),
            "course": c,
            "is_kado": c==kado_course,
            "is_3kado": c==3 and kado_course==3,
            "is_4kado": c==4 and kado_course==4,
            "is_one_outside_kado": kado_course is not None and c==kado_course+1,
            "avg_st_adv_vs_inner": (inner_avg-avg) if avg is not None and inner_avg is not None else None,
            "exhibition_st_adv_vs_inner": (inner_ex-ex) if ex is not None and inner_ex is not None else None,
            "outside_boat": (outer or {}).get("boat") if outer else None,
            "exhibition_time": f(b,"exhibition_time"),
            "motor_rate": f(b,"motor_rate"),
            "local_win_rate": f(b,"local_win_rate"),
            "national_win_rate": f(b,"national_win_rate"),
            "class_rank": b.get("class_rank"),
        })

    return {
        "kado_course": kado_course,
        "is_3kado": kado_course==3,
        "is_4kado": kado_course==4,
        "boats": rows,
        "status": "measurement_only",
        "note": "No production probability adjustment until historical validation estimates effect sizes.",
    }


def interaction_hypotheses() -> list[dict]:
    """Pre-registered hypotheses to test on historical races."""
    return [
        {"id":"KADO_ATTACK", "question":"Does a strong-starting kado boat increase its own 1st/2nd-place rate?"},
        {"id":"OUTSIDE_KADO", "question":"Conditional on kado attack strength, does the immediately outside boat gain 2nd/3rd-place probability?"},
        {"id":"THREE_KADO", "question":"Does 3-kado change the distribution for courses 3/4/5 versus ordinary 3-course slow entry?"},
        {"id":"ABILITY_GATE", "question":"Is the outside-boat benefit conditional on racer/motor ability being sufficient?"},
        {"id":"ST_CHAIN", "question":"Does ST advantage versus the inner boat propagate value to the next outside boat?"},
    ]
