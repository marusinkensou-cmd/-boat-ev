from __future__ import annotations

"""Explicit storage lifecycle for BOAT EV.

TEMP   : operational race/entry/live data; safe to expire when not protected by TRACE.
MASTER : reusable racer facts with as-of provenance; never blind-overwrite history.
TRACE  : immutable/replayable evidence for races actually used by the user.
"""

from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _durable_backup(con):
    """Best-effort durable copy. Runtime must continue if Drive is not configured/unavailable."""
    try:
        from durable_backup_v01 import status, durable_backup
        if status().get('configured'):
            return durable_backup(con)
    except Exception as e:
        print('[DURABLE_BACKUP] MASTER error '+repr(e), flush=True)
    return None


def ensure_lifecycle_schema(con):
    con.execute("""
    CREATE TABLE IF NOT EXISTS racer_master_history (
      racer_id TEXT NOT NULL,
      fact_kind TEXT NOT NULL,
      as_of_date TEXT NOT NULL,
      value_text TEXT,
      source TEXT NOT NULL,
      captured_at TEXT NOT NULL,
      PRIMARY KEY (racer_id, fact_kind, as_of_date, source)
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_racer_master_history_lookup ON racer_master_history(racer_id,fact_kind,as_of_date)")
    con.commit()


def save_master_fact(con, racer_id, fact_kind, as_of_date, value, source):
    """Store a time-addressable MASTER fact without destroying older state."""
    ensure_lifecycle_schema(con)
    con.execute("""INSERT INTO racer_master_history(racer_id,fact_kind,as_of_date,value_text,source,captured_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(racer_id,fact_kind,as_of_date,source) DO UPDATE SET
                     value_text=excluded.value_text,captured_at=excluded.captured_at""",
                (str(racer_id),str(fact_kind),str(as_of_date),None if value is None else str(value),str(source),_now()))
    con.commit()
    _durable_backup(con)


def traced_race_ids(con):
    """Race IDs protected from TEMP cleanup because user evidence exists."""
    protected=set()
    for table in ('race_trace_snapshots','actual_bets','race_settlements'):
        try:
            protected.update(str(r[0]) for r in con.execute(f'SELECT DISTINCT race_id FROM {table}').fetchall())
        except Exception:
            pass
    return protected


def cleanup_temp_before(con, cutoff_date):
    """Expire old operational race/entry rows, never deleting a race protected by TRACE.

    Live odds/beforeinfo tables are intentionally not guessed here: their schemas must be
    explicitly mapped before deletion is enabled. This keeps cleanup conservative.
    """
    protected=traced_race_ids(con)
    rows=con.execute('SELECT race_id FROM races WHERE race_date < ?', (str(cutoff_date),)).fetchall()
    doomed=[str(r[0]) for r in rows if str(r[0]) not in protected]
    deleted_entries=deleted_races=0
    for rid in doomed:
        try:
            deleted_entries += con.execute('DELETE FROM entries WHERE race_id=?',(rid,)).rowcount
        except Exception:
            pass
        deleted_races += con.execute('DELETE FROM races WHERE race_id=?',(rid,)).rowcount
    con.commit()
    return {'cutoff_date':str(cutoff_date),'protected_trace_races':len(protected),'deleted_entries':deleted_entries,'deleted_races':deleted_races}
