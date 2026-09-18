from __future__ import annotations

"""Durable MASTER/TRACE backup foundation for BOAT EV.

SQLite remains the fast runtime store.  This module exports only durable MASTER/TRACE
state to a deterministic JSON document and can restore it after an ephemeral Render
filesystem reset.  Google Drive transport is enabled only when OAuth environment
variables are present; no credentials are committed to GitHub.
"""

import json
import os
import sqlite3
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

SCHEMA_VERSION = 1
DURABLE_TABLES = (
    'racer_master_history',
    'race_trace_snapshots',
    'actual_bets',
    'race_settlements',
)
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file'


def _now():
    return datetime.now(timezone.utc).isoformat()


def _table_exists(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def export_payload(con):
    """Return deterministic, replayable MASTER/TRACE JSON data. TEMP is excluded."""
    tables = {}
    for table in DURABLE_TABLES:
        if not _table_exists(con, table):
            tables[table] = []
            continue
        cur = con.execute('SELECT * FROM "%s"' % table)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        rows.sort(key=lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True, default=str))
        tables[table] = rows
    return {
        'schema_version': SCHEMA_VERSION,
        'exported_at': _now(),
        'data_classes': ['MASTER', 'TRACE'],
        'temp_included': False,
        'tables': tables,
    }


def export_json(con):
    return json.dumps(export_payload(con), ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')


def _pk_columns(con, table):
    info = con.execute('PRAGMA table_info("%s")' % table).fetchall()
    return [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]


def restore_payload(con, payload):
    """Idempotently restore rows into existing schemas; never restores TEMP."""
    if int(payload.get('schema_version', 0)) != SCHEMA_VERSION:
        raise ValueError('unsupported durable backup schema')
    restored = {}
    for table in DURABLE_TABLES:
        rows = payload.get('tables', {}).get(table, [])
        if not rows or not _table_exists(con, table):
            restored[table] = 0
            continue
        existing_cols = {r[1] for r in con.execute('PRAGMA table_info("%s")' % table).fetchall()}
        count = 0
        for row in rows:
            data = {k: v for k, v in row.items() if k in existing_cols}
            if not data:
                continue
            cols = list(data)
            sql = 'INSERT OR REPLACE INTO "%s" (%s) VALUES (%s)' % (
                table, ','.join('"%s"' % c for c in cols), ','.join('?' for _ in cols))
            con.execute(sql, [data[c] for c in cols]); count += 1
        restored[table] = count
    con.commit()
    return {'restored': restored, 'temp_restored': False}


def _oauth_configured():
    return all(os.getenv(k) for k in ('GOOGLE_DRIVE_CLIENT_ID','GOOGLE_DRIVE_CLIENT_SECRET','GOOGLE_DRIVE_REFRESH_TOKEN'))


def _access_token():
    if not _oauth_configured():
        raise RuntimeError('Google Drive OAuth is not configured')
    body = urllib.parse.urlencode({
        'client_id': os.environ['GOOGLE_DRIVE_CLIENT_ID'],
        'client_secret': os.environ['GOOGLE_DRIVE_CLIENT_SECRET'],
        'refresh_token': os.environ['GOOGLE_DRIVE_REFRESH_TOKEN'],
        'grant_type': 'refresh_token',
    }).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())['access_token']
    except urllib.error.HTTPError as e:
        # Preserve Google's OAuth error code/description for diagnosis without logging credentials.
        raw = e.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(raw)
            code = payload.get('error', 'oauth_error')
            desc = payload.get('error_description', '')
            raise RuntimeError('Google OAuth token error: %s%s' % (code, (': ' + desc) if desc else '')) from None
        except json.JSONDecodeError:
            raise RuntimeError('Google OAuth token HTTP %s' % e.code) from None


def _request(url, method='GET', data=None, headers=None):
    h = {'Authorization': 'Bearer ' + _access_token()}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return raw, dict(r.headers)


def _find_backup_file():
    configured = os.getenv('GOOGLE_DRIVE_BACKUP_FILE_ID')
    if configured:
        return configured
    name = os.getenv('GOOGLE_DRIVE_BACKUP_NAME', 'boat-ev-durable-v1.json')
    q = "name='%s' and trashed=false" % name.replace("'", "\\'")
    url = 'https://www.googleapis.com/drive/v3/files?' + urllib.parse.urlencode({'q': q, 'fields': 'files(id,name)', 'pageSize': 10})
    raw, _ = _request(url)
    files = json.loads(raw.decode()).get('files', [])
    return files[0]['id'] if files else None


def drive_backup(con):
    """Create/update one app-owned JSON file. Requires drive.file OAuth."""
    data = export_json(con)
    file_id = _find_backup_file()
    if file_id:
        _request('https://www.googleapis.com/upload/drive/v3/files/%s?uploadType=media' % file_id,
                 method='PATCH', data=data, headers={'Content-Type':'application/json; charset=utf-8'})
        return {'ok': True, 'file_id': file_id, 'bytes': len(data), 'created': False}
    name = os.getenv('GOOGLE_DRIVE_BACKUP_NAME', 'boat-ev-durable-v1.json')
    # Multipart create lets the app own the file, which is compatible with drive.file.
    boundary = 'boat_ev_boundary'
    meta = json.dumps({'name': name}, ensure_ascii=False).encode()
    body = (b'--'+boundary.encode()+b'\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'+meta+
            b'\r\n--'+boundary.encode()+b'\r\nContent-Type: application/json\r\n\r\n'+data+
            b'\r\n--'+boundary.encode()+b'--\r\n')
    raw, _ = _request('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id',
                      method='POST', data=body, headers={'Content-Type':'multipart/related; boundary='+boundary})
    fid = json.loads(raw.decode())['id']
    return {'ok': True, 'file_id': fid, 'bytes': len(data), 'created': True}


def drive_restore(con):
    file_id = _find_backup_file()
    if not file_id:
        return {'ok': True, 'found': False, 'restored': {}}
    raw, _ = _request('https://www.googleapis.com/drive/v3/files/%s?alt=media' % file_id)
    result = restore_payload(con, json.loads(raw.decode('utf-8')))
    result.update({'ok': True, 'found': True, 'file_id': file_id})
    return result


def status():
    return {
        'configured': _oauth_configured(),
        'scope': DRIVE_SCOPE,
        'backup_name': os.getenv('GOOGLE_DRIVE_BACKUP_NAME', 'boat-ev-durable-v1.json'),
        'durable_tables': list(DURABLE_TABLES),
        'temp_included': False,
    }
