using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Dialogs;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows.Input;

namespace PaikkatietoOhje
{
    // AppDomain data uses BCL types so independently loaded add-in assemblies share it.
    // Each DAML declaration has its own IDs; only the elected owner's groups are visible.
    internal static class SharedHelp
    {
        private const string RegistryKey = "Paikkatietotyokalut.SharedHelp.v1";
        private static readonly string[] Keys = { "suomenvaylat", "muuntaja", "liikenneselvitys", "saavutettavuuskartat" };
        private static Dictionary<string, string> Registry
        {
            get
            {
                var result = AppDomain.CurrentDomain.GetData(RegistryKey) as Dictionary<string, string>;
                if (result == null)
                {
                    result = new Dictionary<string, string>(StringComparer.Ordinal);
                    AppDomain.CurrentDomain.SetData(RegistryKey, result);
                }
                return result;
            }
        }

        internal static void Register(string key, Assembly assembly)
        {
            Registry[key] = Path.Combine(Path.GetDirectoryName(assembly.Location), "SharedHelp");
            Refresh();
        }

        internal static void Unregister(string key)
        {
            Registry.Remove(key);
            Refresh();
        }

        private static void Refresh()
        {
            var owner = Keys.FirstOrDefault(Registry.ContainsKey);
            foreach (var key in Keys)
            {
                SetState("PaikkatietoOhje_Owner_" + key, key == owner);
                SetState("PaikkatietoOhje_Tool_" + key, Registry.ContainsKey(key));
            }
        }

        private static void SetState(string state, bool active)
        {
            if (active) FrameworkApplication.State.Activate(state);
            else FrameworkApplication.State.Deactivate(state);
        }

        internal static string NewestGuide(IEnumerable<string> directories)
        {
            var candidates = new List<(long revision, string hash, string path)>();
            foreach (var directory in directories)
            {
                try
                {
                    using var manifest = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "manifest.json")));
                    var root = manifest.RootElement;
                    if (root.GetProperty("schema").GetInt32() != 1) continue;
                    var page = Path.Combine(directory, "index.html");
                    var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(page))).ToLowerInvariant();
                    if (hash != root.GetProperty("sha256").GetString()) continue;
                    candidates.Add((root.GetProperty("revision").GetInt64(), hash, page));
                }
                catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException ||
                    ex is JsonException || ex is KeyNotFoundException || ex is InvalidOperationException || ex is FormatException)
                {
                    Trace.TraceWarning("Paikkatietotyökalujen ohje: " + ex.Message);
                }
            }
            if (candidates.Count == 0) throw new IOException("Ehjää käyttöohjetta ei löytynyt. Asenna lisäosa uudelleen.");
            return candidates.OrderByDescending(c => c.revision).ThenByDescending(c => c.hash, StringComparer.Ordinal)
                .ThenByDescending(c => c.path, StringComparer.Ordinal).First().path;
        }

        internal static void Open()
        {
            try
            {
                var page = NewestGuide(Registry.Values);
                Process.Start(new ProcessStartInfo(new Uri(page).AbsoluteUri) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                MessageBox.Show("Käyttöohje ei avautunut.\n\n" + ex.Message, "Avaa ohje");
            }
        }

        internal static void Execute(string id)
        {
            var command = FrameworkApplication.GetPlugInWrapper(id) as ICommand;
            if (command != null && command.CanExecute(null)) command.Execute(null);
        }
    }

}
