from __future__ import annotations

"""BOAT RACE official trifecta-odds acquisition patch.

Keeps the legacy refresh_one API.  Official PC odds are laid out as six
parallel first-boat columns, so parsing is done from table rows rather than by
flattening the whole page.  Only a complete, self-consistent set of all 120
legal trifecta combinations is persisted.
"""

from datetime import datetime
from html import unescape
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
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _cell_text(cell):
    s = re.sub(r"<[^>]+>", " ", cell)
    s = unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _extract_odds(html):
    """Parse BOAT RACE's six parallel first-boat columns.

    Each first-boat block represents the remaining 5 second boats × 4 third
    boats = 20 odds.  We reconstruct combos from the displayed second/third
    boat labels and validate the legal 120-combination key set before use.
    """
    tables = re.findall(r"<table\b[\s\S]*?</table>", html, flags=re.I)
    best = {}
    for table in tables:
        rows = []
        for tr in re.findall(r"<tr\b[\s\S]*?</tr>", table, flags=re.I):
            cells = [_cell_text(x) for x in re.findall(r"<t[dh]\b[^>]*>([\s\S]*?)</t[dh]>", tr, flags=re.I)]
            if cells:
                rows.append(cells)
        if not rows:
            continue

        # Official desktop table repeats a 4-row third-boat cycle for each
        # second boat and places first boats 1..6 in parallel columns.
        # Instead of depending on CSS classes, read numeric cell streams per
        # first-boat column.  A valid block must reconstruct exactly 20 combos.
        text_rows = rows
        candidate = {}
        # Flatten each row into tokens while preserving row order. The rendered
        # table has groups of (second, third, odds) for each of six first boats.
        for cells in text_rows:
            toks = []
            for c in cells:
                toks.extend(re.findall(r"(?<![0-9.])(?:[1-6]|[0-9]+(?:\.[0-9]+)?)(?![0-9.])", c))
            # Common official row: 18 tokens = 6 × (second, third, odds).
            if len(toks) >= 18:
                # take consecutive triples that are structurally valid; infer
                # first boat from horizontal group index 1..6.
                triples = []
                for i in range(0, min(len(toks), 18), 3):
                    if i + 2 >= len(toks): break
                    triples.append(toks[i:i+3])
                if len(triples) == 6:
                    for first, (second, third, val) in enumerate(triples, start=1):
                        if second not in "123456" or third not in "123456":
                            continue
                        if len({str(first), second, third}) != 3:
                            continue
                        try: odd = float(val)
                        except Exception: continue
                        if odd > 0:
                            candidate[f"{first}{second}{third}"] = odd

        if len(candidate) > len(best):
            best = candidate
        if len(candidate) == 120:
            break

    legal = {f"{a}{b}{c}" for a in range(1,7) for b in range(1,7) for c in range(1,7) if len({a,b,c}) == 3}
    if set(best) != legal:
        return {}
    return best


def _table_columns(con, table):
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def _insert_dynamic(con, table, values):
    cols = _table_columns(con, table)
    if not cols: return False
    use = {k:v for k,v in values.items() if k in cols}
    if not use: return False
    names = list(use)
    con.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(['?']*len(names))})", [use[n] for n in names])
    return True


def refresh_one(con, date, jcd, rno, cache_dir="cache/live"):
    hd = _digits_date(date); jcd = str(jcd).zfill(2); rno = int(rno)
    urls = [
        f"https://www.boatrace.jp/owpc/pc/race/odds3t?hd={hd}&jcd={jcd}&rno={rno}",
        f"https://www.boatrace.jp/owsp/sp/race/odds3t?hd={hd}&jcd={jcd}&rno={rno}",
    ]
    last_error=None; odds={}; source_url=None
    for url in urls:
        try:
            parsed = _extract_odds(_fetch(url))
            if len(parsed) > len(odds): odds, source_url = parsed, url
            if len(parsed) == 120: break
        except Exception as e:
            last_error=str(e)
    captured_at=datetime.now(JST).isoformat()
    if len(odds) != 120:
        return {"ok":False,"status":"NO_ODDS","count":len(odds),"source_url":source_url,"error":last_error}

    race_id=f"{hd}-{jcd}-{rno:02d}"
    stored=0
    try:
        con.execute("BEGIN")
    except Exception: pass
    try:
        if _table_columns(con,"odds_trifecta"):
            for combo, odd in odds.items():
                if _insert_dynamic(con,"odds_trifecta",{
                    "race_id":race_id,"combination":combo,"combo":combo,
                    "odds":odd,"odds_value":odd,"captured_at":captured_at,
                    "fetched_at":captured_at,"source":"boatrace_official","source_url":source_url}): stored += 1
        if _table_columns(con,"odds_snapshots"):
            _insert_dynamic(con,"odds_snapshots",{"race_id":race_id,"captured_at":captured_at,"fetched_at":captured_at,"source":"boatrace_official","source_url":source_url,"count":120})
        con.commit()
    except Exception as e:
        try: con.rollback()
        except Exception: pass
        return {"ok":False,"status":"STORE_ERROR","count":120,"stored":stored,"source_url":source_url,"error":str(e)}
    return {"ok":True,"status":"OK","count":120,"stored":stored,"captured_at":captured_at,"source_url":source_url}
