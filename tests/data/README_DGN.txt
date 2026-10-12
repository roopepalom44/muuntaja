cad_annotations.dgn is GDAL's public test_dgnv8.dgn fixture, redistributed
under GDAL's MIT/X license. It contains synthetic CAD primitives and text.
Source: https://github.com/OSGeo/gdal/blob/master/autotest/ogr/data/dgnv8/test_dgnv8.dgn
License and dgnlib copyright notices are preserved in:
../../qgis_plugin/muuntaja_qgis/vendor/cadkit/GDAL-LICENSE.txt
../../qgis_plugin/muuntaja_qgis/vendor/cadkit/licenses/GDAL-dgnlib-LICENSE.txt

The native ArcGIS regression tests copy it to an isolated temporary folder.
No private client drawing is included. CAD annotation has five records,
one of which has no geometry; the Shapefile export must preserve all five
records and their TextString values. Direct ArcGIS conversion previously
returned zero records; CopyFeatures returned one on the tested runtime.
