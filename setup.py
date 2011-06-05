from distutils.core import setup
import py2exe

setup(windows=[
        {'script': 'guiminer.py',
         'icon_resources': [(0, "logo.ico")]
        }
      ],
      console=['miners/phoenix/phoenix.py', 'poclbm.py', 'po_to_mo.py'],
      # OpenCL.dll is vendor specific
      options=dict(py2exe=dict(
          includes="minerutil, twisted.web.resource, QueueReader",
          dll_excludes=['OpenCL.dll'],
          #bundle_files=1,
          compressed=True,
          optimize=2,
          excludes = ["Tkconstants", "Tkinter", "tcl"],
      )), 
      data_files = ['msvcp90.dll',
                    'BitcoinMiner.cl',
                    'logo.ico',
                    'LICENSE.txt',
                    'servers.ini',
                    'README.txt',
                    'defaults.ini'])
