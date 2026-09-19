from __future__ import annotations

"""Official BOAT RACE trifecta odds adapter for BOAT EV.

Important invariants:
- Read the semantic 20 x 6 oddsPoint matrix, not screen text layout.
- Reconstruct first -> second -> third exactly as BOAT RACE displays it.
- Accept only the complete legal set of 120 trifecta combinations.
- Store using the existing BOAT EV schema: snapshot_id + first/second/third_boat.
"""

import hashlib
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

BASE = "https://www.boatrace.jp/owpc/pc/race"
USER_AGENT = "Mozilla/5.0 (compatible; BOATRACE-EV-Research/1.0)"
MIN_INTERVAL_SEC = 2.0
_last_fetch = 0.0


def official_url(kind, date, jcd, race_no):
    page = {"odds3t": "odds3t", "racelist": "racelist", "beforeinfo": "beforeinfo"}[kind]
    return f"{BASE}/{page}?" + urlencode({"rno": race_no, "jcd": jcd, "hd": date.replace("-", "")})


def fetch_html(url, cache_dir="cache/live", max_age_sec=45, timeout=15):
    global _last_fetch
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / (hashlib.sha256(url.encode()).hexdigest() + ".html")
    if p.exists() and time.time() - p.stat().st_mtime <= max_age_sec:
        return p.read_text(encoding="utf-8", errors="replace"), "cache"
    wait = MIN_INTERVAL_SEC - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.7"})
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
        print(f"[LIVE_FETCH] status={getattr(r,'status',None)} bytes={len(raw)} url={url}", flush=True)
    _last_fetch = time.time()
    text = raw.decode("utf-8", errors="replace")
    p.write_text(text, encoding="utf-8")
    return text, "network"


def _num(s):
    try:
        return float(s.replace(",", "").strip())
    except Exception:
        return None


def parse_deadlines(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    pos = text.find("締切予定時刻")
    target = text[pos:pos+600] if pos >= 0 else text
    times = re.findall(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", target)
    return {i: t for i, t in enumerate(times[:12], 1)}


def parse_trifecta_odds(html):
    """Return {'123': odds, ...} from the official semantic odds matrix.

    The visual design can vary.  We deliberately ignore colors, rowspans and
    rendered grouping.  The official PC table exposes actual odds as
    td.oddsPoint: 20 ordered second/third rows x six first-boat columns.
    """
    soup = BeautifulSoup(html, "html.parser")
    best = None
    for table in soup.find_all("table"):
        rows = []
        for tr in table.select("tbody tr"):
            vals = []
            for td in tr.select("td.oddsPoint"):
                v = _num(td.get_text(" ", strip=True))
                if v is not None and v > 0:
                    vals.append(v)
            if vals:
                rows.append(vals)
        if len(rows) == 20 and all(len(r) == 6 for r in rows):
            best = rows
            break

    if best is None:
        print("[ODDS_PARSE] semantic_matrix_not_found", flush=True)
        raise ValueError("official trifecta semantic matrix not found")

    odds = {}
    for first in range(1, 7):
        vals = [row[first-1] for row in best]
        k = 0
        for second in range(1, 7):
            if second == first:
                continue
            for third in range(1, 7):
                if third == first or third == second:
                    continue
                odds[f"{first}{second}{third}"] = vals[k]
                k += 1

    legal = {
        f"{a}{b}{c}"
        for a in range(1, 7)
        for b in range(1, 7)
        for c in range(1, 7)
        if len({a, b, c}) == 3
    }
    if set(odds) != legal or len(odds) != 120:
        raise ValueError(f"official trifecta reconstruction failed: {len(odds)}/120")
    print(f"[ODDS_PARSE] parsed=120 sample123={odds.get('123')} sample654={odds.get('654')}", flush=True)
    return odds


def upsert_deadlines(con, race_date, jcd, deadlines):
    for rno, t in deadlines.items():
        rid = f"{race_date.replace('-', '')}-{jcd}-{rno:02d}"
        con.execute(
            """INSERT INTO races(race_id,race_date,jcd,race_no,deadline,status)
               VALUES(?,?,?,?,?,'scheduled')
               ON CONFLICT(race_date,jcd,race_no)
               DO UPDATE SET deadline=excluded.deadline""",
            (rid, race_date, jcd, rno, t),
        )
    con.commit()


def store_odds(con, race_id, odds, fetched_at=None):
    fetched_at = fetched_at or datetime.now().astimezone().isoformat(timespec="seconds")
    cur = con.execute("INSERT INTO odds_snapshots(race_id,fetched_at) VALUES(?,?)", (race_id, fetched_at))
    sid = cur.lastrowid
    for combo, val in odds.items():
        a, b, c = map(int, combo)
        con.execute(
            """INSERT INTO odds_trifecta
               (snapshot_id,first_boat,second_boat,third_boat,odds)
               VALUES(?,?,?,?,?)""",
            (sid, a, b, c, val),
        )
    con.commit()
    return sid


def refresh_one(con, race_date, jcd, race_no, cache_dir="cache/live"):
    url = official_url("odds3t", race_date, jcd, race_no)
    html, source = fetch_html(url, cache_dir=cache_dir)
    deadlines = parse_deadlines(html)
    if deadlines:
        upsert_deadlines(con, race_date, jcd, deadlines)
    odds = parse_trifecta_odds(html)
    rid = f"{race_date.replace('-', '')}-{jcd}-{int(race_no):02d}"
    sid = store_odds(con, rid, odds)
    return {"ok": True, "status": "OK", "race_id": rid, "snapshot_id": sid, "odds_count": 120, "source": source, "url": url}
