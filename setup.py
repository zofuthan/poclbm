from distutils.core import setup
import py2exe

setup(#windows=['guiminer.py'],
      console=['guiminer.py', 'poclbm.py'],
      # OpenCL.dll is vendor specific
      options=dict(py2exe=dict(dll_excludes=['OpenCL.dll'])), 
      data_files = ['BitcoinMiner.cl'])
