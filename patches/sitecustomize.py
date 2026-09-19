import importlib.abc
import importlib.util
import os
import shutil
import sys

PATCH_DIR='/opt/render/project/src/patches'
FORCED_PATCH_MODULES={'refresh_service_v13','official_live_v10','preparation_service_v01'}
class _PatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname not in FORCED_PATCH_MODULES:return None
        filename=os.path.join(PATCH_DIR,fullname+'.py')
        return importlib.util.spec_from_file_location(fullname,filename) if os.path.isfile(filename) else None
sys.meta_path.insert(0,_PatchFinder())
if PATCH_DIR in sys.path:sys.path.remove(PATCH_DIR)
sys.path.insert(0,PATCH_DIR)

src=os.path.join(PATCH_DIR,'pwa');dst='/opt/render/project/src/app/pwa'
try:
    if os.path.isdir(src) and os.path.isdir(dst):
        for name in ('index.html','app.js'):shutil.copy2(os.path.join(src,name),os.path.join(dst,name))
        print('[PATCH_PWA] installed focused EV screen',flush=True)
except Exception as e:print('[PATCH_PWA] error '+repr(e),flush=True)

# Restore durable MASTER/TRACE before the HTTP server starts.  No-op until OAuth is configured.
try:
    import sqlite3
    from durable_backup_v01 import status as _durable_status, drive_restore as _drive_restore
    _db='/opt/render/project/src/app/data/boatrace.sqlite'
    if _durable_status().get('configured') and os.path.isfile(_db):
        _con=sqlite3.connect(_db)
        try:
            from data_lifecycle_v01 import ensure_lifecycle_schema
            from race_trace_v01 import ensure_trace_schema
            ensure_lifecycle_schema(_con);ensure_trace_schema(_con)
            print('[DURABLE_RESTORE] '+repr(_drive_restore(_con)),flush=True)
        finally:_con.close()
    else: print('[DURABLE_RESTORE] not configured',flush=True)
except Exception as e: print('[DURABLE_RESTORE] error '+repr(e),flush=True)

server='/opt/render/project/src/app/server_v11.py'
try:
    if os.path.isfile(server):
        text=open(server,encoding='utf-8').read()
        old='''    def board(self):\n        con=sqlite3.connect(self.db)\n        try:\n            now=datetime.now(JST)\n            return {"generated_at":now.isoformat(),"board":build_board(con,now)}\n        finally:\n            con.close()\n'''
        new='''    def board(self):\n        con=sqlite3.connect(self.db)\n        try:\n            now=datetime.now(JST); discovery_error=None
            # User-facing board must be an instant local/cache read. Official network discovery is preparation work.
            board=build_board(con,now)
            # Venue availability must come from today's locally seeded race schedule, not
            # from build_board(), which intentionally exposes only a narrow race window.
            active=[]; seen=set()
            venue_names={str(row.get("jcd","")).zfill(2):row.get("venue") for row in board}
            today=now.date().isoformat()
            rows=con.execute("SELECT jcd,deadline FROM races WHERE race_date=? ORDER BY jcd,race_no",(today,)).fetchall()
            by_venue={}
            for jcd,deadline in rows:
                by_venue.setdefault(str(jcd).zfill(2),[]).append(deadline)
            for j,deadlines in by_venue.items():
                has_remaining=False
                for deadline in deadlines:
                    if not deadline: continue
                    try:
                        if len(str(deadline))<=5:
                            hh,mm=map(int,str(deadline).split(':'))
                            dl=now.replace(hour=hh,minute=mm,second=0,microsecond=0)
                        else:
                            dl=datetime.fromisoformat(str(deadline))
                            if dl.tzinfo is None: dl=dl.replace(tzinfo=JST)
                        if dl>now:
                            has_remaining=True; break
                    except Exception: continue
                if not has_remaining: continue
                active.append({"jcd":j,"venue":venue_names.get(j) or j})
            source="local_today_schedule_with_remaining_race"
            return {"generated_at":now.isoformat(),"active_venues":active,"active_venues_source":source,"discovery_error":discovery_error,"board":board}\n        finally: con.close()\n\n    def prepare_all(self,race_date=None):\n        con=sqlite3.connect(self.db)\n        try:\n            from preparation_service_v01 import prepare_all_venues\n            return prepare_all_venues(con,race_date,"cache/live")\n        finally: con.close()\n'''
        if old in text:text=text.replace(old,new,1)
        elif 'active_venues_source' in text and 'def prepare_all' not in text:
            anchor='    def _set_state(self, **kwargs):\n'
            method=new[new.index('    def prepare_all'):]
            text=text.replace(anchor,method+'\n'+anchor,1)

        route='''            if path=="/api/prepare-all":\n                try:\n                    length=int(self.headers.get("Content-Length","0") or 0); payload={}\n                    if length: payload=json.loads(self.rfile.read(length).decode("utf-8") or "{}")\n                    return self.sendx(200,json.dumps(app.prepare_all(payload.get("race_date")),ensure_ascii=False))\n                except Exception as e:\n                    traceback.print_exc();return self.sendx(500,json.dumps({"error":str(e),"type":type(e).__name__},ensure_ascii=False))\n'''
        marker='            if path=="/api/validation-tick":\n'
        if '/api/prepare-all' not in text:text=text.replace(marker,route+marker,1)
        open(server,'w',encoding='utf-8').write(text)
        print('[PATCH_SERVER] official board + independent all-venue preparation installed',flush=True)
        # Render's local SQLite is rebuilt on deploy. Refill today's TEMP preparation automatically.
        # Run in background so startup and the iPhone board remain nonblocking.
        try:
            import threading
            def _prepare_today_after_boot():
                try:
                    import time; time.sleep(2)
                    import sqlite3
                    from datetime import datetime, timezone, timedelta
                    from preparation_service_v01 import prepare_all_venues
                    _con=sqlite3.connect('/opt/render/project/src/app/data/boatrace.sqlite')
                    try:
                        _today=datetime.now(timezone(timedelta(hours=9))).date().isoformat()
                        print('[BOOT_PREP] start '+_today,flush=True)
                        _res=prepare_all_venues(_con,_today,'cache/live')
                        print('[BOOT_PREP] done '+repr(_res),flush=True)
                    finally:_con.close()
                except Exception as _e:
                    print('[BOOT_PREP] error '+repr(_e),flush=True)
            threading.Thread(target=_prepare_today_after_boot,name='boat-ev-boot-preparation',daemon=True).start()
        except Exception as _e:
            print('[BOOT_PREP] launch_error '+repr(_e),flush=True)
except Exception as e:print('[PATCH_SERVER] error '+repr(e),flush=True)
print('[PATCH_BOOT] forced='+','.join(sorted(FORCED_PATCH_MODULES)),flush=True)
