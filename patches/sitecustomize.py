import sys
PATCH_DIR = '/opt/render/project/src/patches'
if PATCH_DIR in sys.path:
    sys.path.remove(PATCH_DIR)
sys.path.insert(0, PATCH_DIR)
