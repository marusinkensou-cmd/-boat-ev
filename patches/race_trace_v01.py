from __future__ import annotations

"""Canonical per-race trace for BOAT EV.

One race_id owns the chain:
pre-race context -> features -> frozen prediction/odds/EV/recommendation ->
user actual bets -> official result/payout -> settlement.

This module deliberately keeps app recommendations separate from actual bets.
Realized P/L is calculated ONLY from actual bets.
"""

import json
from datetime import datetime, timezone


def ensure_trace_schema(con):
    con.execute("""
    CREATE TABLE IF NOT EXISTS race_trace_snapshots (
      race_id TEXT NOT NULL,
      snapshot_kind TEXT NOT NULL,
      captured_at TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      immutable INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (race_id, snapshot_kind)
    )""")
    con.execute("""
    CREATE TABLE IF NOT EXISTS actual_bets (
      race_id TEXT NOT NULL,
      combo TEXT NOT NULL,
      stake_yen INTEGER NOT NULL,
      placed_at TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'user',
      PRIMARY KEY (race_id, combo)
    )""")
    con.execute("""
    CREATE TABLE IF NOT EXISTS race_settlements (
      race_id TEXT PRIMARY KEY,
      result_combo TEXT,
      payout_per_100_yen INTEGER,
      stake_yen INTEGER NOT NULL DEFAULT 0,
      return_yen INTEGER NOT NULL DEFAULT 0,
      profit_yen INTEGER NOT NULL DEFAULT 0,
      hit INTEGER,
      settled_at TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'official'
    )""")
    con.commit()


def _now():
    return datetime.now(timezone.utc).isoformat()


def save_snapshot(con, race_id: str, kind: str, payload: dict, immutable: bool=False):
    ensure_trace_schema(con)
    old=con.execute("SELECT immutable FROM race_trace_snapshots WHERE race_id=? AND snapshot_kind=?",(race_id,kind)).fetchone()
    if old and int(old[0])==1:
        return {"saved":False,"reason":"immutable"}
    con.execute("""INSERT INTO race_trace_snapshots(race_id,snapshot_kind,captured_at,payload_json,immutable)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(race_id,snapshot_kind) DO UPDATE SET
                     captured_at=excluded.captured_at,payload_json=excluded.payload_json,immutable=excluded.immutable""",
                (race_id,kind,_now(),json.dumps(payload,ensure_ascii=False,separators=(",",":")),1 if immutable else 0))
    con.commit()
    return {"saved":True,"immutable":bool(immutable)}


def freeze_predeadline(con, race_id: str, payload: dict):
    """Freeze the final state that existed before the race result was known."""
    return save_snapshot(con,race_id,"final_predeadline",payload,immutable=True)


def save_actual_bets(con, race_id: str, bets: list[dict]):
    ensure_trace_schema(con)
    now=_now()
    for b in bets:
        combo=str(b["combo"]).replace("-","")
        stake=int(b.get("stake_yen",0))
        if stake<=0: continue
        con.execute("""INSERT INTO actual_bets(race_id,combo,stake_yen,placed_at,source)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(race_id,combo) DO UPDATE SET stake_yen=excluded.stake_yen,placed_at=excluded.placed_at""",
                    (race_id,combo,stake,now,str(b.get("source","user"))))
    con.commit()


def settle_actual_bets(con, race_id: str, result_combo: str, payout_per_100_yen: int):
    """Settle only user actual bets. App recommendations never create P/L."""
    ensure_trace_schema(con)
    result=str(result_combo).replace("-","")
    bets=con.execute("SELECT combo,stake_yen FROM actual_bets WHERE race_id=?",(race_id,)).fetchall()
    stake=sum(int(x[1]) for x in bets)
    win_stake=sum(int(x[1]) for x in bets if str(x[0])==result)
    ret=(win_stake*int(payout_per_100_yen))//100 if win_stake else 0
    profit=ret-stake
    hit=1 if win_stake else 0
    con.execute("""INSERT INTO race_settlements(race_id,result_combo,payout_per_100_yen,stake_yen,return_yen,profit_yen,hit,settled_at,source)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(race_id) DO UPDATE SET
                     result_combo=excluded.result_combo,payout_per_100_yen=excluded.payout_per_100_yen,
                     stake_yen=excluded.stake_yen,return_yen=excluded.return_yen,profit_yen=excluded.profit_yen,
                     hit=excluded.hit,settled_at=excluded.settled_at,source=excluded.source""",
                (race_id,result,int(payout_per_100_yen),stake,ret,profit,hit,_now(),"official"))
    con.commit()
    return {"race_id":race_id,"result_combo":result,"stake_yen":stake,"return_yen":ret,"profit_yen":profit,"hit":bool(hit)}


def cumulative_actual_stats(con):
    ensure_trace_schema(con)
    row=con.execute("SELECT COUNT(*),COALESCE(SUM(stake_yen),0),COALESCE(SUM(return_yen),0),COALESCE(SUM(profit_yen),0),COALESCE(SUM(hit),0) FROM race_settlements").fetchone()
    races,stake,ret,profit,hits=map(int,row)
    return {"settled_races":races,"hits":hits,"stake_yen":stake,"return_yen":ret,"profit_yen":profit,"roi":(ret/stake if stake else None)}
