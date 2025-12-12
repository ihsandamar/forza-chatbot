"""
PyInstaller hook for tiktoken_ext
Ensures all encoding files are collected during the build process
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all data files from tiktoken_ext
datas = collect_data_files('tiktoken_ext')

# Collect all submodules
hiddenimports = collect_submodules('tiktoken_ext')

# Explicitly add the openai_public module which contains the encodings
hiddenimports += [
    'tiktoken_ext.openai_public',
]
