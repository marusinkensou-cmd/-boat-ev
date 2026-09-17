from __future__ import annotations

"""Official BOAT RACE beforeinfo fallback parser.

Purpose: when the legacy live parser returns no exhibition rows after exhibition
publication, fetch the official mobile beforeinfo HTML and recover only fields
that are actually present. No result-page data is used here.
"""

import re
import urllib.request
from html import unescape

UA = "Mozilla/5.0 (BOAT-EV/1.0)"


def official_beforeinfo_url(date_yyyymmdd: str, jcd: str, race_no: int) -> str:
    hd = str(date_yyyymmdd).replace("-", "")
    return f"https://www.boatrace.jp/owsp/sp/race/beforeinfo?hd={hd}&jcd={str(jcd).zfill(2)}&rno={int(race_no)}"


def _text(html: str) -> str:
    s = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()


def fetch_official_beforeinfo(date_yyyymmdd: str, jcd: str, race_no: int, timeout: int = 12) -> dict:
    url = official_beforeinfo_url(date_yyyymmdd, jcd, race_no)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    txt = _text(raw)

    # The official mobile page exposes six exhibition times before the
    # 'スタート展示' section. Keep this conservative: if six values cannot be
    # identified, return not-ready rather than inventing rows.
    head = txt.split("スタート展示", 1)[0]
    times = [float(x) for x in re.findall(r"(?<!\d)([5-8]\.\d{2})(?!\d)", head)]
    # De-duplicate only adjacent repeated rendering artifacts.
    clean_times=[]
    for x in times:
        if not clean_times or x != clean_times[-1]: clean_times.append(x)
    times = clean_times[-6:] if len(clean_times) >= 6 else []

    st=[]
    if "スタート展示" in txt:
        tail=txt.split("スタート展示",1)[1].split("水面気象情報",1)[0]
        for token in re.findall(r"(F\.?\d{1,2}|L\.?\d{1,2}|\.?\d{1,2})", tail):
            t=token.upper()
            sign=-1 if t.startswith("F") else 1
            n=re.sub(r"[^0-9]", "", t)
            if n:
                st.append(sign*(int(n)/100.0))
        st=st[:6]

    weather={}
    for key,pat in {
        "air_temperature":r"気温\s*([0-9.]+)℃",
        "wind_speed":r"風速\s*([0-9.]+)m",
        "water_temperature":r"水温\s*([0-9.]+)℃",
        "wave_height":r"波高\s*([0-9.]+)cm",
    }.items():
        m=re.search(pat,txt)
        if m: weather[key]=float(m.group(1))

    ready=(len(times)==6 and len(st)==6)
    return {
        "source":"boatrace_official_beforeinfo_mobile",
        "url":url,
        "ready":ready,
        "exhibition_times":times,
        "exhibition_st":st,
        "weather":weather,
        "diagnostic":{"times_found":len(times),"st_found":len(st)},
    }
