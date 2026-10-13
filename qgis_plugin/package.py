"""Build an installable QGIS plugin ZIP without caches or test artifacts."""

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import os

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "muuntaja_qgis"
VERSION = next(line.split("=", 1)[1].strip() for line in (PLUGIN / "metadata.txt").read_text(encoding="utf-8").splitlines()
               if line.startswith("version="))
OUTPUT = ROOT / "dist" / f"Muuntaja-QGIS-{VERSION}.zip"
OUTPUT.parent.mkdir(exist_ok=True)
# .exe/.dll: lisäosan mukana jaettava LibreDWG (muuntaja_qgis/libredwg).
ALLOWED = {".py", ".txt", ".png", ".json", ".gpkg", ".exe", ".dll", ".pyd", ".so", ".dgn"}
VENDOR = PLUGIN / "vendor/cadkit"
manifest = json.loads((VENDOR / "manifest.json").read_text(encoding="utf-8"))
for entry in manifest["binaries"].values():
    path = VENDOR / entry["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], path
seed = manifest["seed"]
assert hashlib.sha256((VENDOR / seed["path"]).read_bytes()).hexdigest() == seed["sha256"]
for license_name in ("LICENSE-MIT.txt", "LICENSE-APACHE.txt", "NOTICE.txt", "GDAL-LICENSE.txt"):
    assert (VENDOR / license_name).is_file(), license_name

# ACadSharp-pohjainen DWG-kirjoitin (build_dwgwriter.py); julkaisussa kaikki alustat.
DWG_WRITER = PLUGIN / "acadsharp"
DWG_RIDS = ("win-x64", "linux-x64", "linux-arm64", "osx-x64", "osx-arm64")
for license_name in ("LICENSE-ACadSharp.txt", "LICENSE-dotnet.txt", "ThirdPartyNotices-dotnet.txt", "README.txt"):
    assert (DWG_WRITER / license_name).is_file(), license_name


def dwg_writer_program(rid):
    return DWG_WRITER / rid / ("muuntaja-dwg.exe" if rid.startswith("win") else "muuntaja-dwg")


available = [rid for rid in DWG_RIDS if dwg_writer_program(rid).is_file()]
if os.environ.get("MUUNTAJA_REQUIRE_DWG_WRITER"):
    missing = sorted(set(DWG_RIDS) - set(available))
    assert not missing, f"DWG-kirjoitin puuttuu: {missing} (python qgis_plugin/build_dwgwriter.py)"
elif not available:
    print("Varoitus: DWG-kirjoitinta ei ole käännetty; paketissa ei ole DWG-vientiä.")


def plugin_files(rids):
    for path in sorted(PLUGIN.rglob("*")):
        if not path.is_file():
            continue
        if DWG_WRITER in path.parents and path.parent != DWG_WRITER:
            if path.parent.name in rids and path == dwg_writer_program(path.parent.name):
                yield path
        elif path.suffix.lower() in ALLOWED:
            yield path


with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in plugin_files(available):
        archive.write(path, path.relative_to(ROOT))
with ZipFile(OUTPUT) as archive:
    assert f"{PLUGIN.name}/metadata.txt" in archive.namelist()
    assert f"{PLUGIN.name}/__init__.py" in archive.namelist()
    for entry in manifest["binaries"].values():
        assert f"{PLUGIN.name}/vendor/cadkit/{entry['path']}" in archive.namelist()
    assert f"{PLUGIN.name}/vendor/cadkit/seed3d-metric.dgn" in archive.namelist()
    for tool in ("dwg2dxf.exe", "libredwg-0.dll", "libiconv-2.dll"):
        assert f"{PLUGIN.name}/libredwg/{tool}" in archive.namelist(), tool
    for rid in available:
        assert dwg_writer_program(rid).relative_to(ROOT).as_posix() in archive.namelist(), rid
print(OUTPUT)

WINDOWS_OUTPUT = ROOT / "dist" / f"Muuntaja-QGIS-{VERSION}-Windows.zip"
with ZipFile(WINDOWS_OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    # Windows-paketissa vain Windowsin DWG-kirjoitin, jotta lataus pysyy pienenä.
    for path in plugin_files([rid for rid in available if rid.startswith("win")]):
        archive.write(path, path.relative_to(ROOT))
    archive.write(ROOT / "install_windows.bat", "install_windows.bat")
    archive.write(ROOT / "install_windows.ps1", "install_windows.ps1")
with ZipFile(WINDOWS_OUTPUT) as archive:
    assert archive.testzip() is None
    assert "install_windows.bat" in archive.namelist()
print(WINDOWS_OUTPUT)
