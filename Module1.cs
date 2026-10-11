using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Contracts;

namespace Muuntaja
{
    public class Module1 : Module
    {
        private static Module1 _this = null;

        /// <summary>
        /// Retrieve the singleton instance to this module here
        /// </summary>
        // "Muuntaja_Module" vastaa Config.daml:n insertModule-id:tä.
        public static Module1 Current => _this ??= (Module1)FrameworkApplication.FindModule("Muuntaja_Module");

        #region Overrides
        /// <summary>
        /// Called by Framework when ArcGIS Pro is closing
        /// </summary>
        /// <returns>False to prevent Pro from closing, otherwise True</returns>
        protected override bool CanUnload()
        {
            return true;
        }
        #endregion Overrides
    }
}
