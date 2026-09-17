from __future__ import annotations

"""Venue/environment features for BOAT EV.

This module stores auditable context. It does NOT apply arbitrary probability
boosts. Effects must be estimated from historical/out-of-sample results before
production coefficients are adopted.

Water-type facts follow BOAT RACE terminology: fresh water is generally harder
than sea water; sea water is softer and provides more buoyancy. Fine-grained
ideas such as clarity/pollution -> hardness -> turn grip are retained as
hypotheses unless supported by measurable data.
"""

VENUE_BASE = {
    "01": {"name":"桐生"}, "02": {"name":"戸田"}, "03": {"name":"江戸川"},
    "04": {"name":"平和島"}, "05": {"name":"多摩川"}, "06": {"name":"浜名湖"},
    "07": {"name":"蒲郡"}, "08": {"name":"常滑"}, "09": {"name":"津"},
    "10": {"name":"三国"}, "11": {"name":"びわこ"}, "12": {"name":"住之江"},
    "13": {"name":"尼崎"}, "14": {"name":"鳴門"}, "15": {"name":"丸亀"},
    "16": {"name":"児島"}, "17": {"name":"宮島"}, "18": {"name":"徳山"},
    "19": {"name":"下関"}, "20": {"name":"若松"}, "21": {"name":"芦屋"},
    "22": {"name":"福岡"}, "23": {"name":"唐津"}, "24": {"name":"大村"},
}

# Verified examples are deliberately sparse here; fill the complete 24-venue
# profile only from traceable sources/data rather than guessing.
VERIFIED_WATER = {
    "11": {"water_type":"fresh", "hardness_note":"hard", "source_status":"official_verified"},
    "19": {"water_type":"sea", "source_status":"official_verified"},
    "22": {"water_type":"brackish_near_sea", "source_status":"official_verified"},
}


def build_environment_features(jcd: str, weather: dict | None = None, dynamic: dict | None = None) -> dict:
    jcd=str(jcd).zfill(2)
    weather=weather or {}
    dynamic=dynamic or {}
    base=VENUE_BASE.get(jcd,{"name":jcd})
    water=VERIFIED_WATER.get(jcd,{})
    return {
        "jcd":jcd,
        "venue":base.get("name"),
        "water_type":water.get("water_type"),
        "water_hardness_note":water.get("hardness_note"),
        "water_source_status":water.get("source_status","not_yet_verified"),
        "wind_direction":weather.get("wind_direction") or weather.get("wind_dir"),
        "wind_speed":weather.get("wind_speed"),
        "wave_height":weather.get("wave_height") or weather.get("wave_cm"),
        "air_temperature":weather.get("air_temperature") or weather.get("air_temp"),
        "water_temperature":weather.get("water_temperature") or weather.get("water_temp"),
        "tide_level":dynamic.get("tide_level"),
        "tide_phase":dynamic.get("tide_phase"),
        "current_direction":dynamic.get("current_direction"),
        "water_clarity":dynamic.get("water_clarity"),
        "surface_condition":dynamic.get("surface_condition"),
        "status":"measurement_only",
    }


def environment_hypotheses() -> list[dict]:
    return [
        {"id":"VENUE_COURSE_BASE", "question":"How do 1st/2nd/3rd-place rates by actual course vary by venue and recent period?"},
        {"id":"VENUE_WIND", "question":"How do venue x wind direction/speed interactions change course and winning-technique distributions?"},
        {"id":"VENUE_TIDE", "question":"At tidal venues, how do tide level/phase interact with course and attack style?"},
        {"id":"WATER_TYPE", "question":"Do fresh/sea/brackish water types interact with racer weight, motor performance and turn outcomes?"},
        {"id":"WATER_GRIP", "question":"Does measurable water clarity/quality or an evidence-backed hardness proxy predict turn stability, full-speed turns, makuri or makuri-sashi?"},
        {"id":"VENUE_KADO", "question":"Does the kado/outside-boat interaction effect differ materially by venue and environmental conditions?"},
    ]
