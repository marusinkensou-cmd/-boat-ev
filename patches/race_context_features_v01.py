from __future__ import annotations

"""Additional race-context features for BOAT EV.

These features are measurement-only. They are intended to be attached to the
same race_id trace and validated historically before any production probability
coefficient is adopted.
"""


def _num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _delta(a, b):
    a, b = _num(a), _num(b)
    return None if a is None or b is None else a - b


def build_race_context_features(boats: list[dict], weather: dict | None = None) -> dict:
    weather = weather or {}
    normalized=[]
    for b in boats:
        normalized.append({
            "boat": b.get("boat") or b.get("boat_no"),
            "racer_id": b.get("racer_id"),
            "actual_course": b.get("actual_course") or b.get("course"),
            "avg_st": _num(b.get("avg_st")),
            "exhibition_st": _num(b.get("exhibition_st")),
            "exhibition_time": _num(b.get("exhibition_time")),
            "weight": _num(b.get("weight")),
            "adjust_weight": _num(b.get("adjust_weight")),
            "tilt": _num(b.get("tilt")),
            "propeller_changed": bool(b.get("propeller_changed", False)),
            "parts_changed": b.get("parts_changed") or [],
            "previous_race_no": b.get("previous_race_no"),
            "previous_course": b.get("previous_course"),
            "previous_st": _num(b.get("previous_st")),
            "previous_finish": b.get("previous_finish"),
            "motor_rate": _num(b.get("motor_rate")),
            "local_win_rate": _num(b.get("local_win_rate")),
            "national_win_rate": _num(b.get("national_win_rate")),
            "class_rank": b.get("class_rank"),
        })

    valid_ex=[x["exhibition_time"] for x in normalized if x["exhibition_time"] is not None]
    best_ex=min(valid_ex) if valid_ex else None
    valid_st=[x["exhibition_st"] for x in normalized if x["exhibition_st"] is not None]

    by_course={x["actual_course"]:x for x in normalized if x["actual_course"] is not None}
    for x in normalized:
        x["exhibition_gap_to_best"] = _delta(x["exhibition_time"], best_ex)
        c=x["actual_course"]
        inner=by_course.get(c-1) if isinstance(c, int) and c > 1 else None
        outer=by_course.get(c+1) if isinstance(c, int) and c < 6 else None
        x["exhibition_st_vs_inner"] = _delta(x["exhibition_st"], inner.get("exhibition_st") if inner else None)
        x["exhibition_st_vs_outer"] = _delta(x["exhibition_st"], outer.get("exhibition_st") if outer else None)
        x["avg_st_vs_inner"] = _delta(x["avg_st"], inner.get("avg_st") if inner else None)
        x["same_day_prior_available"] = x["previous_race_no"] is not None
        x["equipment_change"] = bool(x["propeller_changed"] or x["parts_changed"])

    return {
        "boats": normalized,
        "race": {
            "exhibition_best": best_ex,
            "exhibition_st_spread": (max(valid_st)-min(valid_st)) if len(valid_st) >= 2 else None,
            "air_water_temp_gap": _delta(weather.get("air_temperature") or weather.get("air_temp"), weather.get("water_temperature") or weather.get("water_temp")),
            "wind_speed": _num(weather.get("wind_speed")),
            "wave_height": _num(weather.get("wave_height") or weather.get("wave_cm")),
        },
        "status": "measurement_only",
    }


def race_context_hypotheses() -> list[dict]:
    return [
        {"id":"ST_RELATIVE", "question":"Are ST gaps versus adjacent boats more predictive than absolute ST?"},
        {"id":"EXHIBITION_RELATIVE", "question":"Does exhibition-time rank/gap outperform raw exhibition time across venues/seasons?"},
        {"id":"RACER_COURSE_STYLE", "question":"How do racer x actual-course ST and winning-technique tendencies change outcomes?"},
        {"id":"DEEP_ENTRY", "question":"Can entry changes/deep inside starts identify increased dash-side opportunity?"},
        {"id":"MOTOR_STYLE", "question":"Can motor performance be separated into acceleration/turn/straight traits and interacted with course/tactics?"},
        {"id":"EQUIPMENT_CHANGE", "question":"Do propeller/parts changes predict within-meeting performance changes after controlling for racer/motor?"},
        {"id":"SAME_DAY_PRIOR", "question":"Does the same-day prior race improve current estimates of racer/motor adaptation to the water?"},
        {"id":"WEIGHT_ENV", "question":"Does racer/adjustment weight interact with water type, wind and motor traits?"},
        {"id":"TEMP_CHANGE", "question":"Do air/water temperature level and change interact with motor performance?"},
        {"id":"MEETING_TREND", "question":"Can within-meeting exhibition/result trends detect motor setup improvement or deterioration?"},
    ]
