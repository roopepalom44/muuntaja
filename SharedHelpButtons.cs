using ArcGIS.Desktop.Framework.Contracts;
using SharedGuide = global::PaikkatietoOhje.SharedHelp;

// Use the add-in's default namespace. Pro prepends it to every DAML className.
namespace Muuntaja
{
    public sealed class OpenHelpButton : Button { protected override void OnClick() => SharedGuide.Open(); }
    public sealed class SuomenvaylatButton : Button { protected override void OnClick() => SharedGuide.Execute("suomenvaylat_SuomenvaylatButton"); }
    public sealed class MuuntajaButton : Button { protected override void OnClick() => SharedGuide.Execute("Muuntaja_OpenToolButton"); }
    public sealed class LiikenneselvitysButton : Button { protected override void OnClick() => SharedGuide.Execute("Liikenneselvitys_OpenButton"); }
    public sealed class SaavutettavuuskartatButton : Button { protected override void OnClick() => SharedGuide.Execute("Saavutettavuuskartat_OpenButton"); }
}
