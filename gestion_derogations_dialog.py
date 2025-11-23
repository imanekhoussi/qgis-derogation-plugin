import os
import tempfile
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QSize
from PyQt5.QtGui import QImage, QPainter, QTextDocument
from PyQt5.QtWidgets import (QDialog, QFileDialog, QMessageBox, QTableWidgetItem, 
                             QHeaderView)
from qgis.PyQt import uic
from qgis.core import (QgsProject, QgsVectorLayer, QgsGeometry, QgsFeature,
                       QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsMapSettings, QgsMapRendererCustomPainterJob, QgsRectangle,
                       QgsWkbTypes, QgsSymbol)
from qgis.gui import QgsMapToolEmitPoint
from qgis.utils import iface

try:
    from PyQt5.QtPrintSupport import QPrinter
except ImportError:
    pass

# Load the UI file you provided
FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'Derogation_dialog_base.ui'))

# --- CONFIGURATION (Match these to your actual QGIS Layer Names) ---
CONFIG = {
    "CRS_PROJECT": "EPSG:26191", 
    "LAYERS": {
        "DOMAINE_COMMUNAL": "Domaine Communal",
        "DOMAINE_FORESTIER": "Domaine Forestier",
        "DOMIANE_PRIVE_ETAT": "Domaine Privé État",
        "DOMAINE_PUBLIC": "Domaine Public",
        "Derogation_central_13_avril": "Projets Dérogés"
    },
    "MAX_DEROGATIONS": 4
}

class DerogationAnalysis:
    """Handles the heavy GIS lifting"""
    def __init__(self):
        self.project = QgsProject.instance()
        self.buffer_layer = None
        
    def create_buffer(self, point_xy, radius_m):
        # Remove old buffer if exists
        if self.buffer_layer:
            self.project.removeMapLayer(self.buffer_layer.id())

        # Create Geometry
        geom = QgsGeometry.fromPointXY(point_xy).buffer(radius_m, 40)
        
        # Create Visual Layer
        self.buffer_layer = QgsVectorLayer(f"Polygon?crs={CONFIG['CRS_PROJECT']}", "Zone d'Analyse", "memory")
        prov = self.buffer_layer.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(geom)
        prov.addFeatures([feat])
        
        # Style it (Red transparent)
        symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PolygonGeometry)
        symbol.setColor(Qt.red)
        symbol.setOpacity(0.3)
        self.buffer_layer.renderer().setSymbol(symbol)
        
        self.project.addMapLayer(self.buffer_layer)
        return geom, self.buffer_layer

    def analyze_intersections(self, buffer_geom):
        results = {}
        total_area = buffer_geom.area()

        for tech_name, friendly_name in CONFIG["LAYERS"].items():
            # Find layer loosely by name
            layer = None
            for l in self.project.mapLayers().values():
                if tech_name.lower() in l.name().lower():
                    layer = l
                    break
            
            data = {"name": friendly_name, "area": 0.0, "percentage": 0.0, "status": "Clean"}
            
            if layer:
                intersect_area = 0.0
                request = layer.getFeatures(QgsRectangle(buffer_geom.boundingBox()))
                for feature in request:
                    if feature.geometry().intersects(buffer_geom):
                        intersection = feature.geometry().intersection(buffer_geom)
                        intersect_area += intersection.area()

                data["area"] = intersect_area
                data["percentage"] = (intersect_area / total_area * 100) if total_area > 0 else 0
                data["status"] = "⚠️ IMPACT" if intersect_area > 1.0 else "✅ OK"
            else:
                data["status"] = "❌ Non trouvé"
            results[tech_name] = data
        return results

    def check_nearby_derogations(self, buffer_geom):
        # Find derogation layer
        layer = None
        for l in self.project.mapLayers().values():
            if "derogation" in l.name().lower():
                layer = l
                break
        
        if not layer: return -1
        
        count = 0
        for f in layer.getFeatures(QgsRectangle(buffer_geom.boundingBox())):
            if f.geometry().intersects(buffer_geom): count += 1
        return count

class ReportGenerator:
    """Handles PDF generation"""
    @staticmethod
    def capture_map_image(buffer_layer):
        settings = QgsMapSettings()
        layers = [l for l in QgsProject.instance().mapLayers().values()]
        settings.setLayers(layers)
        settings.setDestinationCrs(QgsCoordinateReferenceSystem(CONFIG["CRS_PROJECT"]))
        extent = buffer_layer.extent()
        extent.scale(1.5) 
        settings.setExtent(extent)
        settings.setOutputSize(QSize(800, 600))
        
        image = QImage(QSize(800, 600), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.white)
        painter = QPainter(image)
        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start()
        job.waitForFinished()
        painter.end()
        
        temp_path = os.path.join(tempfile.gettempdir(), "map_capture.png")
        image.save(temp_path)
        return temp_path

    @staticmethod
    def generate_html_report(filepath, results, decision_text, map_path, point, radius):
        rows = ""
        for key, data in results.items():
            color = "#ffebee" if "IMPACT" in data['status'] else "#e8f5e9"
            rows += f"<tr style='background-color:{color}'><td>{data['name']}</td><td>{data['area']:.2f}</td><td>{data['percentage']:.2f}%</td></tr>"

        html = f"""
        <html><head><style>
            body {{ font-family: Arial; padding: 20px; }}
            h1 {{ color: #2e7d32; border-bottom: 2px solid #2e7d32; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ background: #2e7d32; color: white; padding: 10px; }}
            td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
            .decision {{ padding: 15px; font-weight: bold; background: #f1f8e9; border: 1px solid #c5e1a5; margin-top: 20px; color: #33691e; }}
            .error {{ background: #ffebee; color: #c62828; border: 1px solid #ef9a9a; }}
        </style></head><body>
            <h1>Rapport d'Analyse Khémisset</h1>
            <p><b>Localisation:</b> X={point.x():.2f}, Y={point.y():.2f} | <b>Rayon:</b> {radius}m</p>
            <center><img src='{QUrl.fromLocalFile(map_path).toString()}' width='600'></center>
            <h3>Détail des Intersections</h3>
            <table><tr><th>Couche</th><th>Surface (m²)</th><th>Impact (%)</th></tr>{rows}</table>
            <div class='decision { "error" if "REJETÉ" in decision_text else "" }'>
                {decision_text.replace('\n', '<br>')}
            </div>
        </body></html>
        """
        
        doc = QTextDocument()
        doc.setHtml(html)
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(filepath)
        printer.setPageSize(QPrinter.A4)
        doc.print_(printer)

class DerogationDialog(QDialog, FORM_CLASS):
    coordinates_selected = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super(DerogationDialog, self).__init__(parent)
        self.setupUi(self)
        self.logic = DerogationAnalysis()
        self.map_tool = None
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # Initial UI setup based on your XML defaults
        self.setup_ui_defaults()
        self.connect_signals()

    def setup_ui_defaults(self):
        # Table Setup
        self.tableWidget.setColumnCount(3)
        self.tableWidget.setHorizontalHeaderLabels(["Couche", "Surface (m²)", "%"])
        self.tableWidget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        
        # Initial Visibility (Based on your Checkboxes)
        # Assuming you want GeoJSON hidden and Coords shown by default or vice versa
        # Let's enforce Manual Coords mode first
        self.checkBox_2.setChecked(True)
        self.checkBox.setChecked(False)
        self.toggle_inputs()

    def connect_signals(self):
        # Button Connections
        self.selectPointMapButton.clicked.connect(self.toggle_map_tool)
        self.pushButton_2.clicked.connect(self.run_analysis) # Execute button
        self.pushButton_3.clicked.connect(self.select_pdf_output) # PDF Browse
        
        # Sliders and Labels
        self.bufferRadiusSlider.valueChanged.connect(lambda v: self.bufferRadiusValueLabel.setText(f"{v} m"))
        
        # Signal for Map Tool
        self.coordinates_selected.connect(self.set_coordinates)
        
        # Checkboxes (Mutually exclusive logic)
        self.checkBox.clicked.connect(lambda: self.handle_checkboxes("geojson"))
        self.checkBox_2.clicked.connect(lambda: self.handle_checkboxes("coords"))
        
        # PDF Toggle
        self.checkBox_3.stateChanged.connect(self.toggle_pdf_inputs)

    def handle_checkboxes(self, mode):
        """Ensures only one input mode is active"""
        if mode == "geojson":
            self.checkBox_2.setChecked(False)
        else:
            self.checkBox.setChecked(False)
        self.toggle_inputs()

    def toggle_inputs(self):
        """Hides/Shows widgets based on selection"""
        is_geojson = self.checkBox.isChecked()
        is_coords = self.checkBox_2.isChecked()
        
        # GeoJSON Widgets
        self.label.setVisible(is_geojson)
        self.lineEdit.setVisible(is_geojson)
        self.pushButton.setVisible(is_geojson)
        
        # Coord Widgets
        self.label_2.setVisible(is_coords)
        self.lineEdit_2.setVisible(is_coords)
        self.label_3.setVisible(is_coords)
        self.lineEdit_3.setVisible(is_coords)
        self.selectPointMapButton.setVisible(is_coords)

    def toggle_pdf_inputs(self):
        enabled = self.checkBox_3.isChecked()
        self.label_4.setVisible(enabled)
        self.lineEdit_4.setVisible(enabled)
        self.pushButton_3.setVisible(enabled)

    def toggle_map_tool(self):
        canvas = iface.mapCanvas()
        # Toggle logic
        if self.selectPointMapButton.text().startswith("🗺️"):
            self.map_tool = QgsMapToolEmitPoint(canvas)
            self.map_tool.canvasClicked.connect(self.handle_map_click)
            canvas.setMapTool(self.map_tool)
            self.selectPointMapButton.setText("❌ Annuler sélection")
            self.label_7.setText("ℹ️ Cliquez sur la carte pour définir le centre...")
        else:
            if self.map_tool: canvas.unsetMapTool(self.map_tool)
            self.selectPointMapButton.setText("🗺️ Sélectionner sur la carte")
            self.label_7.setText("Prêt.")

    def handle_map_click(self, point, button):
        # Convert to Project CRS
        source_crs = iface.mapCanvas().mapSettings().destinationCrs()
        dest_crs = QgsCoordinateReferenceSystem(CONFIG["CRS_PROJECT"])
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        proj_point = transform.transform(point)
        
        self.coordinates_selected.emit(proj_point.x(), proj_point.y())
        
        # Reset tool
        iface.mapCanvas().unsetMapTool(self.map_tool)
        self.selectPointMapButton.setText("🗺️ Sélectionner sur la carte")

    def set_coordinates(self, x, y):
        self.lineEdit_2.setText(f"{x:.2f}")
        self.lineEdit_3.setText(f"{y:.2f}")
        self.label_7.setText("✅ Coordonnées récupérées.")

    def select_pdf_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer Rapport", "", "PDF (*.pdf)")
        if path: self.lineEdit_4.setText(path)

    def run_analysis(self):
        try:
            # 1. Input Retrieval
            x_text = self.lineEdit_2.text()
            y_text = self.lineEdit_3.text()
            
            if not x_text or not y_text:
                QMessageBox.warning(self, "Attention", "Veuillez entrer des coordonnées valides.")
                return

            point = QgsPointXY(float(x_text), float(y_text))
            radius = self.bufferRadiusSlider.value()
            
            # 2. Processing
            self.label_7.setText("⏳ Analyse en cours...")
            buffer_geom, buffer_layer = self.logic.create_buffer(point, radius)
            
            # Zoom to result
            iface.mapCanvas().setExtent(buffer_layer.extent())
            iface.mapCanvas().refresh()
            
            # 3. Intersection Logic
            results = self.logic.analyze_intersections(buffer_geom)
            derog_count = self.logic.check_nearby_derogations(buffer_geom)
            
            # 4. Fill Table
            self.tableWidget.setRowCount(0)
            for key, data in results.items():
                row = self.tableWidget.rowCount()
                self.tableWidget.insertRow(row)
                self.tableWidget.setItem(row, 0, QTableWidgetItem(data["name"]))
                self.tableWidget.setItem(row, 1, QTableWidgetItem(f"{data['area']:.2f}"))
                
                # Color code percentage
                perc_item = QTableWidgetItem(f"{data['percentage']:.2f}%")
                if data['area'] > 1:
                    perc_item.setBackground(Qt.red)
                    perc_item.setForeground(Qt.white)
                self.tableWidget.setItem(row, 2, perc_item)
            
            # 5. Final Decision Logic
            prive_etat_impact = results.get("DOMIANE_PRIVE_ETAT", {}).get("area", 0) > 1
            
            decision = ""
            if prive_etat_impact:
                decision = "❌ PROJET NON FAVORABLE\n(Impact sur Domaine Privé de l'État)"
                style = "background-color: #ffebee; color: #c62828; border: 2px solid #ef9a9a;"
            elif derog_count > CONFIG["MAX_DEROGATIONS"]:
                decision = f"❌ PROJET NON FAVORABLE\n(Zone saturée: {derog_count} dérogations)"
                style = "background-color: #ffebee; color: #c62828; border: 2px solid #ef9a9a;"
            else:
                decision = "✅ AVIS FAVORABLE"
                style = "background-color: #e8f5e9; color: #2e7d32; border: 2px solid #a5d6a7;"
            
            self.label_7.setText(decision)
            self.label_7.setStyleSheet(f"QLabel {{ {style} border-radius: 8px; padding: 10px; font-weight: bold; }}")

            # 6. PDF Export
            if self.checkBox_3.isChecked():
                pdf_path = self.lineEdit_4.text()
                if pdf_path:
                    img_path = ReportGenerator.capture_map_image(buffer_layer)
                    ReportGenerator.generate_html_report(pdf_path, results, decision, img_path, point, radius)
                    QMessageBox.information(self, "Succès", "Rapport PDF généré avec succès!")
                else:
                    QMessageBox.warning(self, "Attention", "Veuillez choisir un emplacement pour le PDF.")

        except Exception as e:
            self.label_7.setText(f"Erreur critique: {str(e)}")
            print(e)