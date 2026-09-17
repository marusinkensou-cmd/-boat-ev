import importlib.abc
import importlib.util
import os
import shutil
import sys

PATCH_DIR = '/opt/render/project/src/patches'
FORCED_PATCH_MODULES = {'refresh_service_v13','official_live_v10'}

class _PatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in FORCED_PATCH_MODULES:
            return None
        filename = os.path.join(PATCH_DIR, fullname + '.py')
        if not os.path.isfile(filename):
            return None
        return importlib.util.spec_from_file_location(fullname, filename)

sys.meta_path.insert(0, _PatchFinder())
if PATCH_DIR in sys.path: sys.path.remove(PATCH_DIR)
sys.path.insert(0, PATCH_DIR)

# The build unpacks the legacy app from ZIP. Replace only the user-facing PWA
# with the focused EV screen after unpacking, while keeping the proven backend.
src=os.path.join(PATCH_DIR,'pwa')
dst='/opt/render/project/src/app/pwa'
try:
    if os.path.isdir(src) and os.path.isdir(dst):
        for name in ('index.html','app.js'):
            shutil.copy2(os.path.join(src,name),os.path.join(dst,name))
        print('[PATCH_PWA] installed focused EV screen',flush=True)
except Exception as e:
    print('[PATCH_PWA] error '+repr(e),flush=True)

# The board used to infer active venues only from today's local DB. On a fresh
# Render deploy that DB can be empty even while official races are still live.
# Patch App.board so the selector is sourced from BOAT RACE's official daily
# index; race details remain lazy and are seeded only after the user refreshes
# a selected venue.
server='/opt/render/project/src/app/server_v11.py'
try:
    if os.path.isfile(server):
        text=open(server,encoding='utf-8').read()
        old='''    def board(self):\n        con=sqlite3.connect(self.db)\n        try:\n            now=datetime.now(JST)\n            return {"generated_at":now.isoformat(),"board":build_board(con,now)}\n        finally:\n            con.close()\n'''
        new='''    def board(self):\n        con=sqlite3.connect(self.db)\n        try:\n            now=datetime.now(JST)\n            active=[]\n            discovery_error=None\n            try:\n                from today_discovery_v12 import discover_today\n                active,_=discover_today(now.date().isoformat(),"cache/live")\n            except Exception as e:\n                discovery_error=f"{type(e).__name__}: {e}"\n            return {"generated_at":now.isoformat(),"active_venues":active,"active_venues_source":"official_daily_index","discovery_error":discovery_error,"board":build_board(con,now)}\n        finally:\n            con.close()\n'''
        if old in text:
            open(server,'w',encoding='utf-8').write(text.replace(old,new,1))
            print('[PATCH_SERVER] board active venues use official daily index',flush=True)
        elif 'active_venues_source' in text:
            print('[PATCH_SERVER] already installed',flush=True)
        else:
            print('[PATCH_SERVER] target block not found',flush=True)
except Exception as e:
    print('[PATCH_SERVER] error '+repr(e),flush=True)
print('[PATCH_BOOT] forced='+','.join(sorted(FORCED_PATCH_MODULES)),flush=True)
