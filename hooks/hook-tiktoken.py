"""
PyInstaller hook for tiktoken
Ensures all necessary modules and data files are collected
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all data files from tiktoken
datas = collect_data_files('tiktoken')

# Collect all submodules
hiddenimports = collect_submodules('tiktoken')

# Explicitly add critical modules
hiddenimports += [
    'tiktoken.core',
    'tiktoken.load',
    'tiktoken.model',
    'tiktoken.registry',
]
