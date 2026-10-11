"""Build an installable QGIS plugin ZIP without caches or test artifacts."""

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "muuntaja_qgis"
VERSION = next(line.split("=", 1)[1].strip() for line in (PLUGIN / "metadata.txt").read_text(encoding="utf-8").splitlines()
               if line.startswith("version="))
OUTPUT = ROOT / "dist" / f"Muuntaja-QGIS-{VERSION}.zip"
OUTPUT.parent.mkdir(exist_ok=True)
# .exe/.dll: lisäosan mukana jaettava LibreDWG (muuntaja_qgis/libredwg).
ALLOWED = {".py", ".txt", ".png", ".json", ".gpkg", ".exe", ".dll"}
with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED:
            archive.write(path, path.relative_to(ROOT))
with ZipFile(OUTPUT) as archive:
    assert f"{PLUGIN.name}/metadata.txt" in archive.namelist()
    assert f"{PLUGIN.name}/__init__.py" in archive.namelist()
    for tool in ("dwg2dxf.exe", "libredwg-0.dll", "libiconv-2.dll"):
        assert f"{PLUGIN.name}/libredwg/{tool}" in archive.namelist(), tool
print(OUTPUT)

WINDOWS_OUTPUT = ROOT / "dist" / f"Muuntaja-QGIS-{VERSION}-Windows.zip"
with ZipFile(WINDOWS_OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED:
            archive.write(path, path.relative_to(ROOT))
    archive.write(ROOT / "install_windows.bat", "install_windows.bat")
    archive.write(ROOT / "install_windows.ps1", "install_windows.ps1")
with ZipFile(WINDOWS_OUTPUT) as archive:
    assert archive.testzip() is None
    assert "install_windows.bat" in archive.namelist()
print(WINDOWS_OUTPUT)
