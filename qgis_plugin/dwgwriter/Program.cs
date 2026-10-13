// muuntaja-dwg: converts the DXF written by QGIS' own DXF export to DWG.
//
//   muuntaja-dwg <input.dxf> <output.dwg> [--version 2018|2013|2010|2004|2000]
//                [--units-per-mm <map units per paper millimetre>] [--meters]
//
// ACadSharp 3.8 does not write AutoCAD 2007 (AC1021) files.
//
// QGIS writes stroke widths as polyline widths in map units at the symbology
// scale, which turns a 1.6 mm road at 1:5 000 000 into an 8 km wide band in
// CAD. Model space polylines get zero width instead; with --units-per-mm the
// stroke width becomes the nearest CAD line weight. --meters sets the drawing
// units, which QGIS leaves unset. Layers get the most common colour of their
// entities (QGIS writes every layer red).
//
// The drawing content (entities, the blocks they reference, layers, line types
// and text styles) is read with ACadSharp and copied into a fresh document that
// ACadSharp creates itself, so the DWG gets valid tables, layouts and objects
// regardless of the structural details of the source DXF. The written DWG is
// read back and its entity counts are compared with the source before success
// is reported. A JSON report is printed to stdout; errors go to stderr with a
// non-zero exit code.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.IO;
using ACadSharp.Types.Units;

namespace Muuntaja.Dwg
{
    public static class Program
    {
        private static readonly Dictionary<string, ACadVersion> Versions = new Dictionary<string, ACadVersion>(StringComparer.OrdinalIgnoreCase)
        {
            ["2018"] = ACadVersion.AC1032, ["AC1032"] = ACadVersion.AC1032,
            ["2013"] = ACadVersion.AC1027, ["AC1027"] = ACadVersion.AC1027,
            ["2010"] = ACadVersion.AC1024, ["AC1024"] = ACadVersion.AC1024,
            ["2004"] = ACadVersion.AC1018, ["AC1018"] = ACadVersion.AC1018,
            ["2000"] = ACadVersion.AC1015, ["AC1015"] = ACadVersion.AC1015,
        };

        public static int Main(string[] args)
        {
            var warnings = new List<string>();
            try
            {
                var options = ParseArguments(args);
                var (input, output, version) = (options.Input, options.Output, options.Version);
                var source = ReadDxf(input, warnings);
                var document = CopyDrawing(source, version);
                if (options.Meters)
                {
                    document.Header.InsUnits = UnitsType.Meters;
                }
                var strokes = StrokeWidthsToLineWeights(document, options.UnitsPerMillimetre);
                ColourLayersByEntities(document);
                var expected = CountByType(document.Entities);
                var temporary = output + ".muuntaja-tmp";
                try
                {
                    DwgWriter.Write(temporary, document, null, (sender, e) => Collect(e, warnings, "DWG"));
                    var written = DwgReader.Read(temporary, (sender, e) => Collect(e, null, "DWG-tarkistus"));
                    var actual = CountByType(written.Entities);
                    var missing = expected.Where(pair => !actual.TryGetValue(pair.Key, out var count) || count < pair.Value)
                        .Select(pair => $"{pair.Key} {(actual.TryGetValue(pair.Key, out var count) ? count : 0)}/{pair.Value}")
                        .ToList();
                    if (missing.Count > 0)
                    {
                        throw new InvalidDataException("Kirjoitetusta DWG:stä puuttuu kohteita: " + string.Join(", ", missing));
                    }
                    File.Move(temporary, output, overwrite: true);
                    Console.Out.WriteLine(Report(version, actual, written, strokes, warnings));
                    return 0;
                }
                finally
                {
                    if (File.Exists(temporary))
                    {
                        File.Delete(temporary);
                    }
                }
            }
            catch (ArgumentException exc)
            {
                Console.Error.WriteLine(exc.Message);
                return 64;
            }
            catch (Exception exc)
            {
                Console.Error.WriteLine($"DWG-kirjoitus epäonnistui: {exc.GetType().Name}: {exc.Message}");
                return 2;
            }
        }

        private static string Report(ACadVersion version, SortedDictionary<string, int> counts, CadDocument written,
            int strokes, List<string> warnings)
        {
            using var stream = new MemoryStream();
            using (var json = new Utf8JsonWriter(stream))
            {
                json.WriteStartObject();
                json.WriteString("version", version.ToString());
                json.WriteNumber("entities", counts.Values.Sum());
                json.WriteStartObject("by_type");
                foreach (var pair in counts)
                {
                    json.WriteNumber(pair.Key, pair.Value);
                }
                json.WriteEndObject();
                json.WriteNumber("layers", written.Layers.Count);
                json.WriteNumber("stroke_widths", strokes);
                json.WriteNumber("blocks", written.BlockRecords.Count(block => !block.Name.StartsWith("*", StringComparison.Ordinal)));
                json.WriteStartArray("warnings");
                foreach (var warning in warnings.Distinct().Take(50))
                {
                    json.WriteStringValue(warning);
                }
                json.WriteEndArray();
                json.WriteEndObject();
            }
            return Encoding.UTF8.GetString(stream.ToArray());
        }

        private sealed class Options
        {
            public string Input;
            public string Output;
            public ACadVersion Version = ACadVersion.AC1032;
            public double? UnitsPerMillimetre;
            public bool Meters;
        }

        private static Options ParseArguments(string[] args)
        {
            var positional = new List<string>();
            var options = new Options();
            for (var index = 0; index < args.Length; index++)
            {
                if (args[index] == "--version" && index + 1 < args.Length)
                {
                    if (!Versions.TryGetValue(args[++index], out options.Version))
                    {
                        throw new ArgumentException($"Tuntematon DWG-versio: {args[index]} (sallitut: 2000, 2004, 2010, 2013, 2018)");
                    }
                }
                else if (args[index] == "--units-per-mm" && index + 1 < args.Length)
                {
                    if (!double.TryParse(args[++index], NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
                        || !(value > 0) || double.IsInfinity(value))
                    {
                        throw new ArgumentException($"Virheellinen --units-per-mm: {args[index]}");
                    }
                    options.UnitsPerMillimetre = value;
                }
                else if (args[index] == "--meters")
                {
                    options.Meters = true;
                }
                else
                {
                    positional.Add(args[index]);
                }
            }
            if (positional.Count != 2)
            {
                throw new ArgumentException("Käyttö: muuntaja-dwg <input.dxf> <output.dwg> [--version 2018]");
            }
            if (!File.Exists(positional[0]))
            {
                throw new ArgumentException($"DXF-tiedostoa ei löytynyt: {positional[0]}");
            }
            options.Input = positional[0];
            options.Output = positional[1];
            return options;
        }

        private static readonly LineWeightType[] LineWeights = Enum.GetValues(typeof(LineWeightType)).Cast<LineWeightType>()
            .Where(weight => (short)weight >= 0).OrderBy(weight => (short)weight).ToArray();

        /// <summary>Nearest standard CAD line weight (1/100 mm) for a stroke width in millimetres.</summary>
        public static LineWeightType NearestLineWeight(double millimetres)
        {
            var hundredths = millimetres * 100;
            return LineWeights.OrderBy(weight => Math.Abs((short)weight - hundredths)).First();
        }

        /// <summary>
        /// Replaces model space polyline widths with line weights; returns how
        /// many polylines had a width. Block contents (point symbols) keep theirs.
        /// </summary>
        public static int StrokeWidthsToLineWeights(CadDocument document, double? unitsPerMillimetre)
        {
            var changed = 0;
            foreach (var polyline in document.Entities.OfType<LwPolyline>())
            {
                var width = Math.Max(polyline.ConstantWidth,
                    polyline.Vertices.Select(vertex => Math.Max(vertex.StartWidth, vertex.EndWidth)).DefaultIfEmpty(0).Max());
                if (!(width > 0))
                {
                    continue;
                }
                polyline.ConstantWidth = 0;
                foreach (var vertex in polyline.Vertices)
                {
                    vertex.StartWidth = 0;
                    vertex.EndWidth = 0;
                }
                if (unitsPerMillimetre.HasValue)
                {
                    polyline.LineWeight = NearestLineWeight(width / unitsPerMillimetre.Value);
                }
                changed++;
            }
            return changed;
        }

        /// <summary>Gives each layer the most common colour of its model space entities.</summary>
        public static void ColourLayersByEntities(CadDocument document)
        {
            var colours = document.Entities
                .Where(entity => entity.Layer != null && !entity.Color.IsByLayer && !entity.Color.IsByBlock)
                .GroupBy(entity => entity.Layer.Name)
                .ToDictionary(group => group.Key,
                              group => group.GroupBy(entity => entity.Color).OrderByDescending(colour => colour.Count()).First().Key);
            foreach (var layer in document.Layers)
            {
                if (colours.TryGetValue(layer.Name, out var colour))
                {
                    layer.Color = colour;
                }
            }
        }

        private static void Collect(NotificationEventArgs e, List<string> warnings, string stage)
        {
            if (warnings != null && (e.NotificationType == NotificationType.Error || e.NotificationType == NotificationType.Warning))
            {
                warnings.Add($"{stage}: {e.Message}");
            }
        }

        private static CadDocument ReadDxf(string path, List<string> warnings)
        {
            // Latin-1 maps every byte to one char, so the text round-trips byte
            // for byte; ACadSharp decodes it with the code page of the DXF header.
            var lines = File.ReadAllLines(path, Encoding.Latin1);
            var cleaned = DxfTables.RemoveDuplicateEntries(lines, warnings);
            var bytes = Encoding.Latin1.GetBytes(string.Join("\r\n", cleaned) + "\r\n");
            using var reader = new DxfReader(new MemoryStream(bytes), (sender, e) => Collect(e, null, "DXF"));
            reader.Configuration = new DxfReaderConfiguration { Failsafe = true };
            return reader.Read();
        }

        public static CadDocument CopyDrawing(CadDocument source, ACadVersion version)
        {
            var document = new CadDocument(version);
            document.Header.InsUnits = source.Header.InsUnits;
            document.Header.MeasurementUnits = source.Header.MeasurementUnits;
            // QGIS writes the drawing extents; ArcGIS Pro and "zoom extents" use them.
            document.Header.ModelSpaceExtMin = source.Header.ModelSpaceExtMin;
            document.Header.ModelSpaceExtMax = source.Header.ModelSpaceExtMax;
            foreach (var entity in source.Entities.ToList())
            {
                document.Entities.Add((Entity)entity.Clone());
            }
            // Cloned entities bring their own layer copies; restore the source
            // layer properties (QGIS writes a colour per CAD layer).
            foreach (var layer in document.Layers)
            {
                if (source.Layers.TryGetValue(layer.Name, out var original))
                {
                    layer.Color = original.Color;
                    layer.LineWeight = original.LineWeight;
                    layer.IsOn = original.IsOn;
                    if (original.LineType != null && document.LineTypes.TryGetValue(original.LineType.Name, out var lineType))
                    {
                        layer.LineType = lineType;
                    }
                }
            }
            return document;
        }

        public static SortedDictionary<string, int> CountByType(IEnumerable<Entity> entities)
        {
            var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
            foreach (var entity in entities)
            {
                var name = entity.GetType().Name;
                counts[name] = counts.TryGetValue(name, out var count) ? count + 1 : 1;
            }
            return counts;
        }
    }

    public static class DxfTables
    {
        /// <summary>
        /// Drops repeated entries (same table type and name) from the TABLES
        /// section. QGIS can write layer "0" twice when a CAD layer is also
        /// called "0"; ACadSharp rejects such a file.
        /// </summary>
        public static List<string> RemoveDuplicateEntries(IReadOnlyList<string> lines, List<string> warnings)
        {
            var output = new List<string>(lines.Count);
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var inTables = false;
            var index = 0;
            while (index + 1 < lines.Count)
            {
                var code = lines[index].Trim();
                var value = lines[index + 1].Trim();
                if (code == "0" && value == "ENDSEC")
                {
                    inTables = false;
                }
                else if (code == "2" && index >= 2 && lines[index - 2].Trim() == "0" && lines[index - 1].Trim() == "SECTION")
                {
                    inTables = value == "TABLES";
                }
                if (inTables && code == "0" && value != "TABLE" && value != "ENDTAB" && value != "SECTION")
                {
                    var end = index + 2;
                    string name = null;
                    while (end + 1 < lines.Count && lines[end].Trim() != "0")
                    {
                        if (name == null && lines[end].Trim() == "2")
                        {
                            name = lines[end + 1].Trim();
                        }
                        end += 2;
                    }
                    if (name != null && !seen.Add(value + "\u0001" + name))
                    {
                        warnings?.Add($"DXF: toistuva {value}-määrittely '{name}' ohitettiin");
                    }
                    else
                    {
                        for (var line = index; line < end; line++)
                        {
                            output.Add(lines[line]);
                        }
                    }
                    index = end;
                    continue;
                }
                output.Add(lines[index]);
                output.Add(lines[index + 1]);
                index += 2;
            }
            return output;
        }
    }
}
