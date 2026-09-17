import importlib.abc
import importlib.util
import os
import sys

PATCH_DIR = '/opt/render/project/src/patches'

# The service starts with `cd app && python server_v11.py`. Python places the
# script directory (app/) at sys.path[0], so path order alone cannot reliably
# override modules inside app/. Intercept only the modules intentionally patched.
FORCED_PATCH_MODULES = {
    'refresh_service_v13',
    'official_live_v10',
}

class _PatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in FORCED_PATCH_MODULES:
            return None
        filename = os.path.join(PATCH_DIR, fullname + '.py')
        if not os.path.isfile(filename):
            return None
        return importlib.util.spec_from_file_location(fullname, filename)

sys.meta_path.insert(0, _PatchFinder())

# Helper modules that exist only under patches/ remain normally importable.
if PATCH_DIR in sys.path:
    sys.path.remove(PATCH_DIR)
sys.path.insert(0, PATCH_DIR)

print('[PATCH_BOOT] forced=' + ','.join(sorted(FORCED_PATCH_MODULES)), flush=True)
