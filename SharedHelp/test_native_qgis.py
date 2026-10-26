"""Executed by the real QGIS Desktop --code startup hook in an isolated profile."""
from pathlib import Path
import gc
import hashlib
import json
import os
import sys
import traceback
import tempfile
from unittest.mock import patch
from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QDialog
from qgis import utils

# QGIS executes --code without setting __file__ or normal sys.argv.
arguments = QgsApplication.arguments()
ROOT = Path(arguments[arguments.index("--code") + 1]).resolve().parents[1]
OUTPUT = Path(os.environ.get("PAIKKATIETO_HELP_TEST_RESULT", str(Path(tempfile.gettempdir()) / "paikkatieto-native-help-test.json")))
sources = [ROOT.parent / name / "qgis_plugin" for name in ("saavutettavuustyokalu", "liikenneselvitys", "muuntaja", "suomenvaylat")]
sources = [path for path in sources if path.is_dir()]
if ROOT / "qgis_plugin" not in sources:
    sources.append(ROOT / "qgis_plugin")
NAMES = tuple(name for name in ("suomenvaylat_qgis", "muuntaja_qgis", "liikenneselvitys_qgis", "saavutettavuuskartat_qgis")
              if any((source / name / "plugin.py").is_file() and
                     (name != "saavutettavuuskartat_qgis" or (source / name / "dialog.py").is_file())
                     for source in sources))
result = {}
status = 1
try:
    assert NAMES, "No plugin source was found for the native QGIS test"
    assert utils.iface is not None
    result["interface"] = type(utils.iface).__name__
    result["native_main_window"] = utils.iface.mainWindow().metaObject().className()
    assert result["native_main_window"] == "QgisApp", result
    sys.path[:0] = [str(path) for path in sources]
    utils.plugin_paths[:0] = [str(path) for path in sources]
    utils.updateAvailablePlugins()
    expected = (ROOT / "SharedHelp/index.html").read_bytes()
    def help_actions():
        return [a for a in utils.iface.pluginToolBar().actions() if a.objectName() == "Paikkatietotyokalut_AvaaOhje"]
    for name in NAMES:
        assert utils.loadPlugin(name), name
        assert utils.startPlugin(name), name
        gc.collect()
        QgsApplication.processEvents()
        assert len(help_actions()) == 1, (name, len(help_actions()))
    result["plugin_modules"] = {name: utils.plugins[name].__class__.__module__ for name in NAMES}
    result["help_buttons"] = len(help_actions())
    assert utils.iface.pluginToolBar().actions()[-1] is help_actions()[0]
    with patch.object(QDesktopServices, "openUrl", return_value=True) as opened:
        help_actions()[0].trigger()
        QgsApplication.processEvents()
        opened.assert_called_once()
        path = Path(opened.call_args[0][0].toLocalFile())
        assert path.read_bytes() == expected
        result["opened_manual"] = str(path)
        result["manual_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Exercise the four original launchers too, without running an analysis.
    result["tool_dialogs"] = []
    for name in NAMES:
        plugin = utils.plugins[name]
        plugin.action.trigger()
        QgsApplication.processEvents()
        dialog = plugin.dialog
        assert isinstance(dialog, QDialog) and dialog.isVisible(), name
        result["tool_dialogs"].append(dialog.windowTitle())
        dialog.close()
        QgsApplication.processEvents()
    assert utils.unloadPlugin(NAMES[0])
    gc.collect()
    QgsApplication.processEvents()
    if len(NAMES) > 1:
        assert len(help_actions()) == 1
        with patch.object(QDesktopServices, "openUrl", return_value=True) as opened:
            help_actions()[0].trigger()
            QgsApplication.processEvents()
            opened.assert_called_once()
    for name in NAMES[1:]:
        assert utils.unloadPlugin(name)
    QgsApplication.processEvents()
    assert not help_actions()
    result["unload_implementation_and_last_plugin"] = "OK"
    result["success"] = True
    status = 0
except BaseException:
    result["success"] = False
    result["error"] = traceback.format_exc()
finally:
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os._exit(status)
