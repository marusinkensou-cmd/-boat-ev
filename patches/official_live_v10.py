from __future__ import annotations

"""BOAT RACE official trifecta-odds acquisition patch.

This module intentionally keeps the legacy public API: refresh_one(con, date, jcd,
rno, cache_dir).  It is loaded ahead of app/official_live_v10.py by sitecustomize.
Only complete 120-combination snapshots are persisted; partial/empty pages are
never presented as usable odds.
"""

from datetime import datetime
from zoneinfo import ZoneInfo
import re
import urllib.request

JST = ZoneInfo("Asia/Tokyo")


def _digits_date(date):
    return str(date).replace("-", "")[:8]


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BOAT-EV/1.0"})
    with urllib.request.urlopen(req, timeout=12) as res:
        raw = res.read()
    # Official pages are normally UTF-8 now; keep CP932 fallback for safety.
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _extract_odds(html):
    # PC/SP official HTML carries combination/value cells in varying wrappers.
    # Parse visible text after removing tags, then recognize every legal 3-digit
    # permutation followed by a decimal/integer odds value.  Require all 120.
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = re.sub(r"\s+", " ", text)

    out = {}
    # Some layouts print 1,2,3 in separate cells rather than 123.  Accept both
    # compact and whitespace-separated digits, but only distinct 1..6 boats.
    pat = re.compile(r"(?<!\d)([1-6])\s*([1-6])\s*([1-6])\s+([0-9]+(?:\.[0-9]+)?)(?!\d)")
    for m in pat.finditer(text):
        a,b,c,val = m.groups()
        if len({a,b,c}) != 3:
            continue
        try:
            odd = float(val)
        except Exception:
            continue
        if odd <= 0:
            continue
        out[a+b+c] = odd
    return out


def _table_columns(con, table):
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def _insert_dynamic(con, table, values):
    cols = _table_columns(con, table)
    if not cols:
        return False
    use = {k:v for k,v in values.items() if k in cols}
    if not use:
        return False
    names = list(use)
    sql = f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(['?']*len(names))})"
    con.execute(sql, [use[n] for n in names])
    return True


def refresh_one(con, date, jcd, rno, cache_dir="cache/live"):
    hd = _digits_date(date)
    jcd = str(jcd).zfill(2)
    rno = int(rno)
    urls = [
        f"https://www.boatrace.jp/owsp/sp/race/odds3t?hd={hd}&jcd={jcd}&rno={rno}",
        f"https://www.boatrace.jp/owpc/pc/race/odds3t?hd={hd}&jcd={jcd}&rno={rno}",
    ]
    last_error = None
    odds = {}
    source_url = None
    for url in urls:
        try:
            html = _fetch(url)
            parsed = _extract_odds(html)
            if len(parsed) > len(odds):
                odds, source_url = parsed, url
            if len(parsed) == 120:
                break
        except Exception as e:
            last_error = str(e)

    captured_at = datetime.now(JST).isoformat()
    if len(odds) != 120:
        return {"ok": False, "status": "NO_ODDS", "count": len(odds), "source_url": source_url, "error": last_error}

    race_id = f"{hd}-{jcd}-{rno:02d}"
    # Adapt to the existing DB instead of assuming one historical schema.
    try:
        con.execute("BEGIN")
    except Exception:
        pass
    stored = 0
    try:
        cols = _table_columns(con, "odds_trifecta")
        if cols:
            # Prefer one row per combination. Common legacy aliases are supplied.
            for combo, odd in odds.items():
                values = {
                    "race_id": race_id, "combination": combo, "combo": combo,
                    "odds": odd, "odds_value": odd,
                    "captured_at": captured_at, "fetched_at": captured_at,
                    "source": "boatrace_official", "source_url": source_url,
                }
                if _insert_dynamic(con, "odds_trifecta", values):
                    stored += 1
        # Snapshot metadata is best-effort; EV primarily needs odds_trifecta.
        snap_cols = _table_columns(con, "odds_snapshots")
        if snap_cols:
            _insert_dynamic(con, "odds_snapshots", {
                "race_id": race_id, "captured_at": captured_at,
                "fetched_at": captured_at, "source": "boatrace_official",
                "source_url": source_url, "count": 120,
            })
        con.commit()
    except Exception as e:
        try: con.rollback()
        except Exception: pass
        return {"ok": False, "status": "STORE_ERROR", "count": 120, "stored": stored, "source_url": source_url, "error": str(e)}

    return {"ok": True, "status": "OK", "count": 120, "stored": stored, "captured_at": captured_at, "source_url": source_url}
