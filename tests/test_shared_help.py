"""Run shared offline-manual regressions in the repository's normal test suite."""
from pathlib import Path
import importlib.util

_path = Path(__file__).resolve().parents[1] / 'SharedHelp' / 'test_shared_help.py'
_spec = importlib.util.spec_from_file_location('common_manual_tests', _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
GuideTests = _module.GuideTests