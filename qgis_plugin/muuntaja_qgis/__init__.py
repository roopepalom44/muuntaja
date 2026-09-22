"""QGIS entry point for Muuntaja."""


def classFactory(iface):
    from .plugin import MuuntajaPlugin
    return MuuntajaPlugin(iface)
