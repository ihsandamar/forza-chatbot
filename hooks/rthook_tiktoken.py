"""
Runtime hook for tiktoken to ensure encoding files are found in frozen environment
This hook sets up the correct paths for tiktoken to find its encoding data files
"""
import os
import sys

# When running as a PyInstaller bundle, ensure tiktoken can find its encoding files
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running in a PyInstaller bundle
    bundle_dir = sys._MEIPASS

    # Set environment variable to help tiktoken find encodings
    tiktoken_cache_dir = os.path.join(bundle_dir, 'tiktoken_ext', 'openai_public')
    if os.path.exists(tiktoken_cache_dir):
        os.environ['TIKTOKEN_CACHE_DIR'] = tiktoken_cache_dir
