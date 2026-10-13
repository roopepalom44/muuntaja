"""Build the bundled ACadSharp DWG writer (muuntaja-dwg) for the QGIS plugin.

    python qgis_plugin/build_dwgwriter.py                  # all platforms
    python qgis_plugin/build_dwgwriter.py --rid linux-x64  # one platform

Requires the .NET 8 SDK. Each platform gets a self-contained single-file
program in qgis_plugin/muuntaja_qgis/acadsharp/<rid>/, so QGIS users need no
.NET installation.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "dwgwriter" / "MuuntajaDwg.csproj"
OUTPUT = ROOT / "muuntaja_qgis" / "acadsharp"
RIDS = ("win-x64", "linux-x64", "linux-arm64", "osx-x64", "osx-arm64")


def build(rid):
    target = OUTPUT / rid
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(["dotnet", "publish", str(PROJECT), "-c", "Release", "-r", rid, "-o", str(target),
                    "-nologo", "-v", "q"], check=True)
    name = "muuntaja-dwg.exe" if rid.startswith("win") else "muuntaja-dwg"
    program = target / name
    if not program.is_file():
        raise SystemExit(f"Build produced no {program}")
    for extra in target.iterdir():
        if extra != program:
            extra.unlink() if extra.is_file() else shutil.rmtree(extra)
    print(f"{rid}: {program} ({program.stat().st_size // 1024} KiB)")
    return program


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rid", action="append", choices=RIDS, help="platform to build (repeatable)")
    for rid in parser.parse_args().rid or RIDS:
        build(rid)


if __name__ == "__main__":
    sys.exit(main())
