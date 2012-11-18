from distutils.core import setup
import py2exe

setup(windows=[
        {'script': 'guiminer.py',
         'icon_resources': [(0, "logo.ico")]
        }
      ],
      console=['phoenix.py', 'poclbm.py', 'po_to_mo.py'],
      # OpenCL.dll is vendor specific
      options=dict(py2exe=dict(
          includes="minerutil, twisted.web.resource, QueueReader",
          dll_excludes=['OpenCL.dll', 'w9xpopen.exe', 'boost_python-vc90-mt-1_39.dll'],
          #bundle_files=1,
          compressed=True,
          optimize=2,
          excludes = ["Tkconstants", "Tkinter", "tcl", "curses", "_ssl", "pyexpat", "unicodedata", "bz2"],
      )), 
      data_files = ['msvcp90.dll',
                    'phatk.cl',
                    'logo.ico',
                    'LICENSE.txt',
                    'servers.ini',
                    'README.txt',
                    'defaults.ini'])