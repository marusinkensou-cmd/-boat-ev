from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')


def prepare_all_venues(con, race_date=None, cache_dir='cache/live'):
    """Prepare TEMP race/entry data for every officially published venue.

    TEMP preparation must never create TRACE prediction snapshots, freeze a race,
    settle a race, or mark a race as user-used. Reusable racer facts belong in
    MASTER and are added separately with temporal provenance.
    """
    from today_discovery_v12 import discover_today
    from racelist_live_v12 import seed_venue_races, refresh_racelist
    from data_lifecycle_v01 import ensure_lifecycle_schema

    ensure_lifecycle_schema(con)
    race_date = race_date or datetime.now(JST).date().isoformat()
    venues, discovery_meta = discover_today(race_date, cache_dir)
    result = {
        'ok': True,
        'race_date': race_date,
        'data_class': 'TEMP',
        'scope': 'all_officially_published_venues',
        'history_effect': 'none',
        'trace_created': False,
        'venues': [],
        'errors': [],
        'discovery': discovery_meta,
    }

    for venue in venues:
        jcd = str(venue.get('jcd', '')).zfill(2)
        name = venue.get('venue') or jcd
        item = {'jcd': jcd, 'venue': name, 'races_seeded': 0, 'entries_prepared': 0, 'entry_errors': []}
        try:
            count = con.execute(
                'SELECT COUNT(*) FROM races WHERE race_date=? AND jcd=? AND deadline IS NOT NULL',
                (race_date, jcd),
            ).fetchone()[0]
            if count == 0:
                seed_venue_races(con, race_date, jcd, cache_dir)
            rows = con.execute(
                'SELECT race_id,race_no FROM races WHERE race_date=? AND jcd=? AND deadline IS NOT NULL ORDER BY race_no',
                (race_date, jcd),
            ).fetchall()
            item['races_seeded'] = len(rows)
            for race_id, race_no in rows:
                entry_count = con.execute('SELECT COUNT(*) FROM entries WHERE race_id=?', (race_id,)).fetchone()[0]
                if entry_count < 6:
                    try:
                        refresh_racelist(con, race_date, jcd, race_no, cache_dir)
                        entry_count = con.execute('SELECT COUNT(*) FROM entries WHERE race_id=?', (race_id,)).fetchone()[0]
                    except Exception as exc:
                        item['entry_errors'].append({'race_no': race_no, 'error': str(exc)})
                if entry_count >= 6:
                    item['entries_prepared'] += 1
            con.commit()
        except Exception as exc:
            result['errors'].append({'jcd': jcd, 'error': str(exc)})
        result['venues'].append(item)

    result['ok'] = not result['errors']
    result['venues_found'] = len(venues)
    result['races_prepared'] = sum(v['entries_prepared'] for v in result['venues'])
    return result
