import importlib.abc
import importlib.util
import os
import shutil
import sys

PATCH_DIR='/opt/render/project/src/patches'
FORCED_PATCH_MODULES={'refresh_service_v13','official_live_v10'}
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

server='/opt/render/project/src/app/server_v11.py'
try:
    if os.path.isfile(server):
        text=open(server,encoding='utf-8').read()
        old='''    def board(self):\n        con=sqlite3.connect(self.db)\n        try:\n            now=datetime.now(JST)\n            return {"generated_at":now.isoformat(),"board":build_board(con,now)}\n        finally:\n            con.close()\n'''
        new='''    def board(self):\n        con=sqlite3.connect(self.db)\n        try:\n            now=datetime.now(JST); active=[]; discovery_error=None\n            try:\n                from today_discovery_v12 import discover_today\n                active,_=discover_today(now.date().isoformat(),"cache/live")\n            except Exception as e: discovery_error=f"{type(e).__name__}: {e}"\n            return {"generated_at":now.isoformat(),"active_venues":active,"active_venues_source":"official_daily_index","discovery_error":discovery_error,"board":build_board(con,now)}\n        finally: con.close()\n\n    def prepare_venue(self,jcd):\n        jcd=str(jcd).zfill(2); con=sqlite3.connect(self.db)\n        try:\n            from racelist_live_v12 import seed_venue_races,refresh_racelist\n            now=datetime.now(JST); today=now.date().isoformat()\n            cnt=con.execute("SELECT COUNT(*) FROM races WHERE race_date=? AND jcd=? AND deadline IS NOT NULL",(today,jcd)).fetchone()[0]\n            if cnt==0: seed_venue_races(con,today,jcd,"cache/live")\n            rows=con.execute("SELECT race_id,race_no,deadline FROM races WHERE race_date=? AND jcd=? AND deadline IS NOT NULL ORDER BY race_no",(today,jcd)).fetchall()\n            future=[]\n            for rid,rno,dl in rows:\n                try:\n                    hh,mm=map(int,dl[:5].split(':')); t=now.replace(hour=hh,minute=mm,second=0,microsecond=0)\n                    if t>now: future.append((rid,rno))\n                except Exception: pass\n            prepared=[]\n            for rid,rno in future[:2]:\n                ec=con.execute("SELECT COUNT(*) FROM entries WHERE race_id=?",(rid,)).fetchone()[0]\n                if ec<6: refresh_racelist(con,today,jcd,rno,"cache/live")\n                prepared.append(rno)\n            return {"ok":True,"jcd":jcd,"prepared_races":prepared}\n        finally: con.close()\n'''
        if old in text:text=text.replace(old,new,1)
        elif 'active_venues_source' in text and 'def prepare_venue' not in text:
            anchor='    def _set_state(self, **kwargs):\n'
            method=new[new.index('    def prepare_venue'):]
            text=text.replace(anchor,method+'\n'+anchor,1)
        # Add a dedicated PREP endpoint. It may take time, but it runs before the user presses Update.
        route='''            if path=="/api/prepare":\n                try:\n                    length=int(self.headers.get("Content-Length","0") or 0); payload={}\n                    if length: payload=json.loads(self.rfile.read(length).decode("utf-8") or "{}")\n                    jcd=payload.get("jcd")\n                    if not jcd:return self.sendx(400,json.dumps({"error":"jcd required"}))\n                    return self.sendx(200,json.dumps(app.prepare_venue(jcd),ensure_ascii=False))\n                except Exception as e:\n                    traceback.print_exc();return self.sendx(500,json.dumps({"error":str(e),"type":type(e).__name__},ensure_ascii=False))\n'''
        marker='            if path=="/api/validation-tick":\n'
        if '/api/prepare' not in text:text=text.replace(marker,route+marker,1)
        open(server,'w',encoding='utf-8').write(text)
        print('[PATCH_SERVER] official board + pre-update preparation endpoint installed',flush=True)
except Exception as e:print('[PATCH_SERVER] error '+repr(e),flush=True)
print('[PATCH_BOOT] forced='+','.join(sorted(FORCED_PATCH_MODULES)),flush=True)
