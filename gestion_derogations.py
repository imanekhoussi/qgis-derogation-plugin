import os.path
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from .gestion_derogations_dialog import DerogationDialog

class GestionDerogationsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dlg = None
        self.action = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), "Analyse Dérogation", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Gestion Dérogations", self.action)

    def unload(self):
        self.iface.removePluginMenu("&Gestion Dérogations", self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        if not self.dlg:
            self.dlg = DerogationDialog()
        self.dlg.show()
        self.dlg.activateWindow()