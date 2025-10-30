"""
PyInstaller hook for chromadb
Automatically collects all chromadb submodules
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import pkgutil
import chromadb

# Method 1: Use collect_submodules
hiddenimports = collect_submodules('chromadb')

# Method 2: Walk packages manually to catch everything
def collect_all_chromadb_modules():
    """Manually walk all chromadb packages"""
    modules = []
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=chromadb.__path__,
        prefix=chromadb.__name__ + '.',
        onerror=lambda x: None
    ):
        modules.append(modname)
    return modules

# Add manually collected modules
manual_modules = collect_all_chromadb_modules()
hiddenimports.extend(manual_modules)

# Remove duplicates and test modules
hiddenimports = list(set(hiddenimports))
hiddenimports = [m for m in hiddenimports if '.test' not in m]

# Critical modules that might be missed
critical_modules = [
    'chromadb.execution.executor',
    'chromadb.execution.executor.local',
    'chromadb.migrations.embeddings_queue',
    'chromadb.segment.impl.metadata',
    'chromadb.segment.impl.metadata.sqlite',
]

for module in critical_modules:
    if module not in hiddenimports:
        hiddenimports.append(module)

# Collect data files (if any)
datas = collect_data_files('chromadb', include_py_files=False)

print(f"[HOOK] Collected {len(hiddenimports)} chromadb modules (including critical modules)")
print(f"[HOOK] Critical modules added: {len([m for m in critical_modules if m in hiddenimports])}/{len(critical_modules)}")
