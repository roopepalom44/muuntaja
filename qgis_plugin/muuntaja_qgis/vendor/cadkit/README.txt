Bundled pycadkit 0.3.0: self-contained DGN V7/V8 reader and DGN V8 writer.
Source: https://github.com/TNYCL/cadkit
Release: https://pypi.org/project/pycadkit/0.3.0/
License: MIT OR Apache-2.0. See LICENSE-MIT.txt, LICENSE-APACHE.txt and NOTICE.txt.
SBOM.json contains the upstream Windows wheel's Rust dependency inventory.
PROVENANCE.txt preserves upstream attributions. licenses/ contains the Rust
dependency license texts and notices for ported ACadSharp, ezdgn and GDAL code.

The platform-specific CPython stable-ABI extension modules are extracted from
the official Python 3.9+ wheels. manifest.json pins each original wheel URL,
its SHA-256 checksum and the extracted binary checksum. package.py verifies
the checksums before packaging. dgn.py loads the extension privately; it does
not install packages, change QGIS Python or import another plugin's cadkit.
Windows x64, Linux x64/ARM64 and macOS Intel/Apple Silicon are included.

seed3d-metric.dgn is derived from GDAL's MIT-licensed test_dgnv8.dgn:
https://github.com/OSGeo/gdal/blob/master/autotest/ogr/data/dgnv8/test_dgnv8.dgn
The original fixture SHA-256 and resulting seed SHA-256 are in manifest.json.
See GDAL-LICENSE.txt for GDAL's license terms. No Esri installation resources,
Bentley SDK or ODA SDK binary is bundled. The fixture's original producer
metadata and unused definitions may remain, but its model has no geometry.
To derive the seed using cadkit 0.3.0: read the fixture, empty the model's
entities, layers and blocks, clear document/model properties and warnings,
then call Document.from_json(...).to_dgn(original_bytes, options_json) with
clear_seed_model=true, preserve_seed_rasters=false, preserve_seed_controls=false.
The resulting model is 3D, meters, 10,000 UOR per meter (0.1 mm resolution).

DGN V8 writing is a subset in upstream cadkit. See:
https://github.com/TNYCL/cadkit/blob/main/docs/dgn/FORMAT_NOTES.md
https://github.com/TNYCL/cadkit/blob/main/docs/INTERCHANGE_STATUS.md
Muuntaja validates selection, CRS transformation, Z, text and polygon holes
in real QGIS. ArcGIS Pro independently recognizes exported geometries and
holes; newly created level names are currently absent from its Layer field,
and hole-cell insertion points also appear in its CAD Point class.
MicroStation acceptance is not certified. Unsupported reads report warnings.
