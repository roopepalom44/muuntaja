using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Xml.Linq;

// Read CLR metadata without loading the SDK or running any add-in code.
// ArcGIS Pro prefixes className with Config.daml's defaultNamespace, including
// dotted relative names. A successful C# build alone cannot validate this link.
if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: TypeCheck assembly.dll Config.daml");
    return 2;
}
using var stream = File.OpenRead(args[0]);
using var pe = new PEReader(stream);
var metadata = pe.GetMetadataReader();
var types = new HashSet<string>(StringComparer.Ordinal);
foreach (var handle in metadata.TypeDefinitions)
{
    var definition = metadata.GetTypeDefinition(handle);
    if ((definition.Attributes & TypeAttributes.Abstract) != 0) continue;
    types.Add(metadata.GetString(definition.Namespace) + "." + metadata.GetString(definition.Name));
}
var daml = XDocument.Load(args[1]);
var root = daml.Root ?? throw new InvalidDataException("Config.daml has no root element");
var prefix = (string)root.Attribute("defaultNamespace") ?? "";
var checkedCount = 0;
var missing = new List<string>();
foreach (var element in root.Descendants().Where(e => e.Attribute("className") != null))
{
    var expected = string.IsNullOrEmpty(prefix) ? (string)element.Attribute("className")
        : prefix + "." + (string)element.Attribute("className");
    checkedCount++;
    if (!types.Contains(expected)) missing.Add(expected);
}
if (checkedCount == 0 || missing.Count > 0)
{
    Console.Error.WriteLine("DAML/CLR type validation failed. ArcGIS Pro cannot load these classes:");
    foreach (var name in missing) Console.Error.WriteLine("  " + name);
    return 1;
}
Console.WriteLine($"DAML/CLR: all {checkedCount} declared classes exist in {Path.GetFileName(args[0])}");
return 0;
