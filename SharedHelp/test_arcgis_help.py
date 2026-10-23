"""Exercise the real C# helper in four independent assemblies against SDK stubs.

This verifies cross-add-in BCL state sharing and guide selection, not the live
ArcGIS ribbon. Requires .NET 8 SDK; generates all build files in a temporary dir.
"""
from pathlib import Path
from html import escape
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
STUB = r'''
using System.Collections.Generic;
using System.Windows.Input;
namespace ArcGIS.Desktop.Framework.Contracts {
    public class Button { protected virtual void OnClick() {} }
}
namespace ArcGIS.Desktop.Framework.Dialogs {
    public static class MessageBox { public static void Show(string message, string title) { throw new System.Exception(message); } }
}
namespace ArcGIS.Desktop.Framework {
    public class States {
        public HashSet<string> Active = new HashSet<string>();
        public void Activate(string key) { Active.Add(key); }
        public void Deactivate(string key) { Active.Remove(key); }
    }
    public static class FrameworkApplication {
        public static States State = new States();
        public static string LastId;
        public static object GetPlugInWrapper(string id) { LastId = id; return null; }
    }
}
'''
PROGRAM = r'''
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using ArcGIS.Desktop.Framework;
class Program {
    static readonly string[] Keys = {"suomenvaylat", "muuntaja", "liikenneselvitys", "saavutettavuuskartat"};
    static MethodInfo Method(Assembly a, string name) => a.GetType("PaikkatietoOhje.SharedHelp").GetMethod(name, BindingFlags.Static | BindingFlags.NonPublic);
    static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    static IEnumerable<int[]> Orders(int[] values) {
        if (values.Length == 0) { yield return values; yield break; }
        foreach (var first in values)
            foreach (var rest in Orders(values.Where(i => i != first).ToArray()))
                yield return new [] { first }.Concat(rest).ToArray();
    }
    static void Main(string[] args) {
        var assemblies = args.Select(Assembly.LoadFrom).ToArray();
        int scenarios = 0;
        foreach (var order in Orders(new[]{0,1,2,3})) {
            var registered = new HashSet<int>();
            foreach (var i in order) {
                Method(assemblies[i], "Register").Invoke(null, new object[]{ Keys[i], assemblies[i] });
                registered.Add(i);
                var owner = registered.Min();
                foreach (var j in Enumerable.Range(0,4)) {
                    Check(FrameworkApplication.State.Active.Contains("PaikkatietoOhje_Owner_" + Keys[j]) == (j == owner), "Duplicate/missing owner");
                    Check(FrameworkApplication.State.Active.Contains("PaikkatietoOhje_Tool_" + Keys[j]) == registered.Contains(j), "Wrong tool state");
                }
                scenarios++;
            }
            foreach (var i in order.Reverse())
                Method(assemblies[(i+1)%4], "Unregister").Invoke(null, new object[]{Keys[i]});
            Check(FrameworkApplication.State.Active.Count == 0, "Unregister left active states");
        }
        var dirs = assemblies.Select((a,i) => Path.Combine(Path.GetDirectoryName(a.Location), "GuideFixture"+i)).ToArray();
        for (var i=0; i<4; i++) {
            Directory.CreateDirectory(dirs[i]);
            var data = System.Text.Encoding.UTF8.GetBytes("ohje-"+i);
            File.WriteAllBytes(Path.Combine(dirs[i], "index.html"), data);
            File.WriteAllText(Path.Combine(dirs[i], "manifest.json"), JsonSerializer.Serialize(new {schema=1, revision=9+i, sha256=Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant()}));
        }
        foreach (var a in assemblies) {
            var chosen = (string)Method(a,"NewestGuide").Invoke(null,new object[]{dirs.Reverse()});
            Check(chosen == Path.Combine(dirs[3], "index.html"), "Newest revision was not selected");
        }
        File.WriteAllText(Path.Combine(dirs[3],"index.html"),"damaged");
        Check((string)Method(assemblies[0],"NewestGuide").Invoke(null,new object[]{dirs}) == Path.Combine(dirs[2],"index.html"), "Corrupt copy not skipped");
        Method(assemblies[0],"Execute").Invoke(null,new object[]{"Muuntaja_OpenToolButton"});
        Check(FrameworkApplication.LastId == "Muuntaja_OpenToolButton", "Original command not used");
        Console.WriteLine($"C#: {scenarios} registration states across 24 orders, cross-assembly unload, newest guide and corrupt fallback OK");
    }
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix="shared-help-csharp-") as temporary:
        root = Path(temporary)
        stub = root / "Stub"
        stub.mkdir()
        project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>{}</Project>'
        (stub / "Stub.csproj").write_text(project.format(""), encoding="utf-8")
        (stub / "Stub.cs").write_text(STUB, encoding="utf-8")
        for i in range(4):
            tool = root / f"Tool{i}"
            tool.mkdir()
            items = f'<ItemGroup><ProjectReference Include="../Stub/Stub.csproj"/><Compile Include="{escape(str(ROOT / "SharedHelp.cs"))}" Link="SharedHelp.cs"/></ItemGroup>'
            (tool / f"Tool{i}.csproj").write_text(project.format(items), encoding="utf-8")
        host = root / "Host"
        host.mkdir()
        refs = '<ItemGroup><ProjectReference Include="../Stub/Stub.csproj"/>' + ''.join(f'<ProjectReference Include="../Tool{i}/Tool{i}.csproj"/>' for i in range(4)) + '</ItemGroup>'
        (host / "Host.csproj").write_text(project.format(refs).replace('<TargetFramework>', '<OutputType>Exe</OutputType><TargetFramework>'), encoding="utf-8")
        (host / "Program.cs").write_text(PROGRAM, encoding="utf-8")
        paths = [str(root / f"Tool{i}/bin/Debug/net8.0/Tool{i}.dll") for i in range(4)]
        subprocess.run(["dotnet", "run", "--project", str(host), "--verbosity", "quiet", "--", *paths], check=True)


if __name__ == "__main__":
    main()
