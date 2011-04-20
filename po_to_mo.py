import os, sys

import polib

def get_module_path():
    """Return the folder containing this script (or its .exe)."""
    module_name = sys.executable if hasattr(sys, 'frozen') else __file__
    abs_path = os.path.abspath(module_name)
    return os.path.dirname(abs_path)

po = polib.pofile('guiminer_ru.po')
path = os.path.join(get_module_path(), 'locale', 'ru', 'LC_MESSAGES', 'guiminer.mo')
try:
    po.save_as_mofile(path)
except:
    print "Couldn't save file"
    raise
else:
    print "Save OK. Press any key to continue."
    raw_input()
