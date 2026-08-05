using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGIS.Desktop.Framework.Dialogs;
using System;
using System.IO;
using System.Reflection;

namespace Muuntaja // <-- KORJATTU
{
    public class OpenMuuntajaToolButton : Button
    {
        protected override void OnClick()
        {
            try
            {
                // 1) Add-inin asennuskansio (dll:n sijainti)
                var asmPath = Assembly.GetExecutingAssembly().Location;
                var addinFolder = Path.GetDirectoryName(asmPath);

                // 2) Toolbox (.pyt) add-inin mukana
                var pytPath = Path.Combine(addinFolder, "Toolboxes", "Muuntaja.pyt");

                if (!File.Exists(pytPath))
                {
                    MessageBox.Show(
                        $"Toolboxia ei löytynyt:\n{pytPath}\n\nVarmista, että Muuntaja.pyt on mukana projektissa ja paketoituu add-iniin (Build Action: Content).",
                        "Muuntaja");
                    return;
                }

                // 3) Tool name = python toolboxin tool-classin nimi
                var toolName = "UniversalImportTool";

                // 4) Custom GP tool path: <toolbox path>\\<tool name>
                var toolPath = Path.Combine(pytPath, toolName);

                // 5) Avaa työkalu geoprocessing-paneeliin
                Geoprocessing.OpenToolDialog(toolPath, null, null, false);

                // 6) Lokitetaan työkalun avaus
                _ = LogData.GetInstance("", "UniversalImportTool", "Muuntaja");
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString(), "Muuntaja - virhe");
            }
        }
    }
}
