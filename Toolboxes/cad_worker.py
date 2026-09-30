"""Muuntajan CAD-lukijan erillinen prosessi; kutsutaan Python-työkalulaatikosta."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import arcpy


class Messages:
    def __init__(self):
        self.entries = []

    def addMessage(self, text):
        self.entries.append(("INFO", text))

    def addWarningMessage(self, text):
        self.entries.append(("WARNING", text))

    def addErrorMessage(self, text):
        self.entries.append(("ERROR", text))


def spatial_reference(text):
    if not text:
        return None
    sr = arcpy.SpatialReference()
    sr.loadFromString(text)
    return sr


def main(request_path, result_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    loader = importlib.machinery.SourceFileLoader("muuntaja_cad_worker", str(Path(__file__).with_name("Muuntaja.pyt")))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    tool = module.UniversalImportTool()
    messages = Messages()
    paths = []
    result = {"paths": paths, "messages": messages.entries}
    tool._add_layers_to_map = lambda saved, _messages, _styles=None: paths.extend(saved)
    try:
        gdb = str(arcpy.management.CreateFileGDB(request["work_dir"], "cad.gdb")[0])
        with arcpy.EnvManager(scratchWorkspace=gdb, addOutputsToMap=False, overwriteOutput=False):
            tool._process_cad_in_process(
                request["input_path"], gdb, False, request["use_mapper"],
                spatial_reference(request["input_sr"]), spatial_reference(request["target_sr"]), messages,
            )
            tool._run_deferred_cleanup(messages)
    except Exception as error:
        result["error"] = str(error)
    finally:
        try:
            arcpy.management.ClearWorkspaceCache()
        except Exception:
            pass
        Path(result_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
