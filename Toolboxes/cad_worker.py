"""Read CAD in an isolated ArcGIS Python process; communicate using JSON files."""

import importlib.machinery
import importlib.util
import json
import os
import sys


def main(request_path, result_path):
    result = {"paths": [], "messages": []}

    class Messages:
        def addMessage(self, text):
            result["messages"].append(("INFO", text))

        def addWarningMessage(self, text):
            result["messages"].append(("WARNING", text))

        def addErrorMessage(self, text):
            result["messages"].append(("ERROR", text))

    try:
        import arcpy
        with open(request_path, encoding="utf-8") as stream:
            request = json.load(stream)
        loader = importlib.machinery.SourceFileLoader("muuntaja_cad_toolbox", os.path.join(os.path.dirname(__file__), "Muuntaja.pyt"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        tool = module.UniversalImportTool()
        output = os.path.join(request["work_dir"], "cad.gdb")
        arcpy.management.CreateFileGDB(request["work_dir"], "cad.gdb")
        # Keep intermediates inside this request's folder, separate from outputs.
        arcpy.management.CreateFileGDB(request["work_dir"], "scratch.gdb")
        arcpy.env.scratchWorkspace = os.path.join(request["work_dir"], "scratch.gdb")
        arcpy.env.addOutputsToMap = False
        tool._add_layers_to_map = lambda paths, messages, styles=None: result["paths"].extend(paths)

        def spatial_reference(text):
            if not text:
                return None
            sr = arcpy.SpatialReference()
            sr.loadFromString(text)
            return sr

        tool._process_cad_in_process(request["input_path"], output, False, request["use_mapper"],
                                    spatial_reference(request["input_sr"]),
                                    spatial_reference(request["target_sr"]), Messages())
        tool._run_deferred_cleanup(Messages())
        arcpy.management.ClearWorkspaceCache()
    except Exception as exc:
        result["error"] = str(exc)
    with open(result_path, "w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False)
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
