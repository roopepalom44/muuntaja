muuntaja-dwg: DXF → DWG writer for the Muuntaja QGIS plugin.

Source: ../../dwgwriter (C#, .NET 8). Built with qgis_plugin/build_dwgwriter.py
as one self-contained single-file program per platform:

  win-x64/muuntaja-dwg.exe, linux-x64/muuntaja-dwg, linux-arm64/muuntaja-dwg,
  osx-x64/muuntaja-dwg, osx-arm64/muuntaja-dwg

No .NET installation is needed. The program reads the DXF written by QGIS' own
DXF export, copies its entities, blocks, layers, line types and text styles
into a new ACadSharp document and writes AutoCAD 2000/2004/2010/2013/2018 DWG.
The written DWG is read back and its entity counts are checked before the file
is accepted.

Third-party components:
- ACadSharp 3.8.0, https://github.com/DomCR/ACadSharp, MIT License,
  Copyright (c) 2021 Albert Domenech. See LICENSE-ACadSharp.txt.
- .NET 8 runtime (self-contained, trimmed), https://github.com/dotnet/runtime,
  MIT License, Copyright (c) .NET Foundation and Contributors.
  See LICENSE-dotnet.txt and ThirdPartyNotices-dotnet.txt.

The binaries are not stored in git; CI builds them for every release.
