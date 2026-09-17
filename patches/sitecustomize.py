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
print('[PATCH_BOOT] forced='+','.join(sorted(FORCED_PATCH_MODULES)),flush=True)
