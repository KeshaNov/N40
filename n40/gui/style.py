"""Оформление в духе модернизма: бумажный фон, чёрная графика, плоские формы,
основные цвета Баухауза как функциональные акценты (красный — резка, синий — гравировка,
жёлтый — выделение / область раскроя)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

PAPER = "#F2EFE8"
PAPER_2 = "#E6E2D8"
INK = "#111111"
GREY = "#8A8780"
RED = "#E1301C"
BLUE = "#1E4FD8"
YELLOW = "#F2BE22"
BED = "#FFFFFF"
OUTSIDE = "#D9D5CB"

MODE_COLORS = {"cut": RED, "engrave": BLUE, "raster": INK}

FONT_FAMILY = "Segoe UI"

QSS = f"""
* {{
    font-family: "{FONT_FAMILY}", "Arial";
    font-size: 9pt;
    color: {INK};
}}
QMainWindow, QDialog, QWizard, QWidget#Panel {{ background: {PAPER}; }}
QToolTip {{ background: {INK}; color: {PAPER}; border: none; padding: 4px 6px; }}

QMenuBar {{ background: {PAPER}; border-bottom: 2px solid {INK}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {INK}; color: {PAPER}; }}
QMenu {{ background: {PAPER}; border: 2px solid {INK}; padding: 4px 0; }}
QMenu::item {{ padding: 5px 28px 5px 16px; }}
QMenu::item:selected {{ background: {INK}; color: {PAPER}; }}
QMenu::separator {{ height: 1px; background: {INK}; margin: 4px 0; }}

QToolBar {{ background: {PAPER}; border: none; spacing: 0; padding: 0; }}
QToolBar#Tools {{ border-right: 2px solid {INK}; padding: 6px 4px; }}
QToolBar#Actions {{ border-bottom: 1px solid {INK}; padding: 3px 6px; }}
QToolBar::separator {{ background: {INK}; width: 1px; height: 1px; margin: 6px 6px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; padding: 5px; margin: 1px; }}
QToolButton:hover {{ border: 1px solid {INK}; }}
QToolButton:checked {{ background: {INK}; }}
QToolButton:pressed {{ background: {YELLOW}; }}

QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {INK}; color: {PAPER}; padding: 6px 10px; text-align: left; }}

QTabWidget::pane {{ border: none; border-top: 2px solid {INK}; background: {PAPER}; }}
QTabBar::tab {{ background: {PAPER}; padding: 7px 12px; border: none; margin-right: 2px;
               font-weight: 600; letter-spacing: 1px; }}
QTabBar::tab:selected {{ background: {INK}; color: {PAPER}; }}
QTabBar::tab:hover:!selected {{ background: {PAPER_2}; }}

QGroupBox {{ border: none; border-top: 1px solid {INK}; margin-top: 18px; padding-top: 8px;
             font-weight: 700; letter-spacing: 1px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 0; top: 2px; padding: 0; text-transform: uppercase; }}

QPushButton {{ background: {PAPER}; border: 2px solid {INK}; padding: 6px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {PAPER_2}; }}
QPushButton:pressed {{ background: {YELLOW}; }}
QPushButton:disabled {{ color: {GREY}; border-color: {GREY}; }}
QPushButton#Primary {{ background: {INK}; color: {PAPER}; }}
QPushButton#Primary:hover {{ background: #333; }}
QPushButton#Danger {{ background: {RED}; color: white; border-color: {RED}; }}
QPushButton#Danger:hover {{ background: #C02615; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QFontComboBox {{
    background: white; border: 1px solid {INK}; padding: 4px 6px; selection-background-color: {YELLOW};
    selection-color: {INK};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 2px solid {INK}; padding: 3px 5px; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: white; border: 2px solid {INK}; selection-background-color: {INK};
                               selection-color: {PAPER}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; }}

QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {INK}; background: white; }}
QCheckBox::indicator:checked {{ background: {INK}; image: none; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QRadioButton::indicator:checked {{ background: {INK}; }}

QSlider::groove:horizontal {{ height: 2px; background: {INK}; }}
QSlider::handle:horizontal {{ background: {RED}; width: 12px; height: 12px; margin: -6px 0; }}

QProgressBar {{ border: 2px solid {INK}; background: white; height: 14px; text-align: center; font-weight: 600; }}
QProgressBar::chunk {{ background: {RED}; }}

QListWidget, QTreeWidget, QTableWidget {{ background: {PAPER}; border: none; outline: none; }}
QListWidget::item {{ border-bottom: 1px solid {PAPER_2}; padding: 4px; }}
QListWidget::item:selected {{ background: {INK}; color: {PAPER}; }}
QHeaderView::section {{ background: {PAPER}; border: none; border-bottom: 1px solid {INK}; padding: 4px; font-weight: 700; }}
QTableWidget {{ gridline-color: {PAPER_2}; }}

QStatusBar {{ background: {INK}; color: {PAPER}; }}
QStatusBar QLabel {{ color: {PAPER}; padding: 0 10px; }}

QScrollBar:vertical {{ width: 10px; background: {PAPER}; }}
QScrollBar:horizontal {{ height: 10px; background: {PAPER}; }}
QScrollBar::handle {{ background: {GREY}; min-height: 30px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QLabel#Title {{ font-size: 20pt; font-weight: 800; letter-spacing: -1px; }}
QLabel#Caption {{ color: {GREY}; text-transform: uppercase; letter-spacing: 1px; font-size: 8pt; }}
QLabel#Big {{ font-size: 22pt; font-weight: 800; }}
QLabel#State {{ font-size: 12pt; font-weight: 800; }}

/* левая колонка: разделы как в Bambu Studio */
QScrollArea#Sidebar, QWidget#SidebarBody {{ background: {PAPER}; border: none; }}
QPushButton#SectionHeader {{ background: {INK}; color: {PAPER}; border: none; padding: 7px 12px; margin: 0;
                             font-weight: 700; letter-spacing: 2px; text-align: left; }}
QPushButton#SectionHeader:hover {{ background: #2A2A2A; }}
QPushButton#SectionHeader:pressed {{ background: {INK}; }}
QPushButton#Square {{ padding: 0; min-width: 30px; max-width: 30px; min-height: 26px; font-size: 12pt; }}
QPushButton#Jog, QPushButton#JogHome {{ padding: 0; font-size: 16pt; font-weight: 400; }}
QPushButton#JogHome {{ background: {INK}; color: {PAPER}; }}
QPushButton#JogHome:hover {{ background: #333; }}
QPushButton#Step {{ padding: 0; font-weight: 600; }}
QPushButton#Step:checked {{ background: {INK}; color: {PAPER}; }}

/* шапка: управление заданием */
QPushButton#HeaderButton {{ background: transparent; color: {PAPER}; border: 1px solid {GREY}; padding: 4px 14px; }}
QPushButton#HeaderButton:hover {{ border-color: {PAPER}; }}
QPushButton#HeaderButton:checked {{ background: {PAPER}; color: {INK}; }}
QPushButton#HeaderStop {{ background: {RED}; color: white; border: none; padding: 4px 16px; }}
QPushButton#HeaderStop:hover {{ background: #C02615; }}
QPushButton#HeaderStart {{ background: {YELLOW}; color: {INK}; border: none; padding: 4px 22px; font-weight: 800; }}
QPushButton#HeaderStart:hover {{ background: #FFD24A; }}
QProgressBar#HeaderProgress {{ border: 1px solid {GREY}; background: transparent; max-height: 6px; }}
QLabel#HeaderInfo {{ color: {GREY}; }}
QToolBar#Actions QToolButton {{ padding: 4px; }}
"""


def ui_font(size: float = 9, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


# --------------------------------------------------------------------------- иконки

def _icon(draw, size: int = 22) -> QIcon:
    icon = QIcon()
    for state, color in ((QIcon.State.Off, INK), (QIcon.State.On, PAPER)):
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 1.6)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        draw(p, size, QColor(color))
        p.end()
        icon.addPixmap(pm, QIcon.Mode.Normal, state)
    return icon


def make_icon(name: str) -> QIcon:
    s = 22

    def poly(p, pts):
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))

    def accent(p, color, shape):
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(RED) if color.name().upper() == INK.upper() else QColor(YELLOW))
        shape()
        p.restore()

    def d(p, size, color):
        m = 4
        if name == "select":
            path = QPainterPath()
            path.moveTo(6, 3); path.lineTo(6, 18); path.lineTo(10, 14); path.lineTo(13, 20)
            path.lineTo(15, 19); path.lineTo(12, 13); path.lineTo(17, 13); path.closeSubpath()
            p.setBrush(color); p.drawPath(path)
        elif name == "rect":
            p.drawRect(QRectF(m, m + 2, s - 2 * m, s - 2 * m - 4))
        elif name == "rrect":
            p.drawRoundedRect(QRectF(m, m + 2, s - 2 * m, s - 2 * m - 4), 4, 4)
        elif name == "ellipse":
            p.drawEllipse(QRectF(m, m + 3, s - 2 * m, s - 2 * m - 6))
        elif name == "circle":
            p.drawEllipse(QRectF(m, m, s - 2 * m, s - 2 * m))
        elif name == "line":
            p.drawLine(QPointF(m, s - m), QPointF(s - m, m))
            accent(p, color, lambda: (p.drawRect(QRectF(m - 2, s - m - 2, 4, 4)), p.drawRect(QRectF(s - m - 2, m - 2, 4, 4))))
        elif name == "polyline":
            poly(p, [(4, 17), (8, 5), (14, 12), (18, 4), (18, 18)])
        elif name == "ngon":
            poly(p, [(11, 3), (19, 9), (16, 19), (6, 19), (3, 9)])
        elif name == "text":
            p.setFont(ui_font(13, True)); p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "Т")
        elif name == "region":
            pen = p.pen(); pen.setStyle(Qt.PenStyle.DashLine); p.setPen(pen)
            poly(p, [(3, 5), (17, 3), (19, 17), (6, 19)])
        elif name == "forbid":
            p.drawRect(QRectF(4, 4, 14, 14)); p.drawLine(QPointF(4, 4), QPointF(18, 18)); p.drawLine(QPointF(18, 4), QPointF(4, 18))
        elif name == "import":
            p.drawLine(QPointF(11, 3), QPointF(11, 14)); poly(p, [(7, 10), (11, 14), (15, 10)])
            p.drawLine(QPointF(4, 18), QPointF(18, 18))
        elif name == "nest":
            p.drawRect(QRectF(3, 3, 16, 16))
            accent(p, color, lambda: (p.drawRect(QRectF(5, 5, 6, 6)), p.drawEllipse(QRectF(12, 11, 6, 6))))
            p.drawRect(QRectF(5, 13, 5, 4))
        elif name == "union":
            p.setBrush(color); p.drawEllipse(QRectF(3, 6, 10, 10)); p.drawEllipse(QRectF(9, 6, 10, 10))
        elif name == "difference":
            p.setBrush(color); p.drawEllipse(QRectF(3, 6, 10, 10)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(QRectF(9, 6, 10, 10))
        elif name == "intersection":
            p.drawEllipse(QRectF(3, 6, 10, 10)); p.drawEllipse(QRectF(9, 6, 10, 10))
            clip = QPainterPath(); clip.addEllipse(QRectF(3, 6, 10, 10))
            other = QPainterPath(); other.addEllipse(QRectF(9, 6, 10, 10))
            p.fillPath(clip.intersected(other), color)
        elif name == "rot_cw":
            p.drawArc(QRectF(4, 4, 14, 14), 90 * 16, -270 * 16); poly(p, [(18, 8), (18, 13), (14, 11)])
        elif name == "rot_ccw":
            p.drawArc(QRectF(4, 4, 14, 14), 90 * 16, 270 * 16); poly(p, [(4, 8), (4, 13), (8, 11)])
        elif name == "flip_h":
            p.drawLine(QPointF(11, 2), QPointF(11, 20)); poly(p, [(3, 16), (9, 6), (9, 16)])
            p.setBrush(color); poly(p, [(19, 16), (13, 6), (13, 16)])
        elif name == "flip_v":
            p.drawLine(QPointF(2, 11), QPointF(20, 11)); poly(p, [(6, 3), (16, 9), (6, 9)])
            p.setBrush(color); poly(p, [(6, 19), (16, 13), (6, 13)])
        elif name.startswith("align_"):
            kind = name[6:]
            bars = {"left": [(4, 5, 12), (4, 13, 7)], "right": [(6, 5, 12), (11, 13, 7)],
                    "hcenter": [(5, 5, 12), (7.5, 13, 7)], "top": None, "bottom": None, "vcenter": None}
            if kind in ("left", "right", "hcenter"):
                x = {"left": 3, "right": 19, "hcenter": 11}[kind]
                p.drawLine(QPointF(x, 2), QPointF(x, 20))
                p.setBrush(color)
                for bx, by, bw in bars[kind]:
                    p.drawRect(QRectF(bx, by, bw, 4))
            else:
                y = {"top": 3, "bottom": 19, "vcenter": 11}[kind]
                p.drawLine(QPointF(2, y), QPointF(20, y))
                p.setBrush(color)
                if kind == "top":
                    p.drawRect(QRectF(5, 4, 4, 12)); p.drawRect(QRectF(13, 4, 4, 7))
                elif kind == "bottom":
                    p.drawRect(QRectF(5, 6, 4, 12)); p.drawRect(QRectF(13, 11, 4, 7))
                else:
                    p.drawRect(QRectF(5, 5, 4, 12)); p.drawRect(QRectF(13, 7.5, 4, 7))
        elif name == "dist_h":
            p.setBrush(color)
            for x in (3, 9.5, 16):
                p.drawRect(QRectF(x, 6, 3, 10))
        elif name == "dist_v":
            p.setBrush(color)
            for y in (3, 9.5, 16):
                p.drawRect(QRectF(6, y, 10, 3))
        elif name == "group":
            pen = p.pen(); pen.setStyle(Qt.PenStyle.DotLine); p.setPen(pen); p.drawRect(QRectF(2, 2, 18, 18))
            pen.setStyle(Qt.PenStyle.SolidLine); p.setPen(pen); p.drawRect(QRectF(5, 5, 7, 7)); p.drawEllipse(QRectF(10, 10, 7, 7))
        elif name == "ungroup":
            p.drawRect(QRectF(3, 3, 7, 7)); p.drawEllipse(QRectF(12, 12, 7, 7))
        elif name == "array":
            for i in range(3):
                for j in range(3):
                    p.drawRect(QRectF(3 + i * 6, 3 + j * 6, 4, 4))
        elif name == "carray":
            import math
            for k in range(8):
                a = k * math.pi / 4
                p.drawEllipse(QPointF(11 + 7 * math.cos(a), 11 + 7 * math.sin(a)), 1.8, 1.8)
        elif name == "offset":
            p.drawRect(QRectF(7, 7, 8, 8))
            pen = p.pen(); pen.setStyle(Qt.PenStyle.DashLine); p.setPen(pen); p.drawRoundedRect(QRectF(3, 3, 16, 16), 4, 4)
        elif name == "camera":
            p.drawRect(QRectF(3, 7, 16, 11)); p.drawEllipse(QRectF(8, 9, 6, 6)); p.drawRect(QRectF(7, 4, 6, 3))
        elif name == "laser":
            accent(p, color, lambda: poly(p, [(11, 2), (15, 10), (7, 10)]))
            p.drawLine(QPointF(11, 10), QPointF(11, 19))
            p.drawLine(QPointF(6, 19), QPointF(16, 19))
        elif name == "delete":
            p.drawLine(QPointF(5, 5), QPointF(17, 17)); p.drawLine(QPointF(17, 5), QPointF(5, 17))
        elif name == "duplicate":
            p.drawRect(QRectF(3, 3, 11, 11)); p.setBrush(color); p.drawRect(QRectF(8, 8, 11, 11))
        elif name == "gear":
            import math
            for k in range(8):
                a = k * math.pi / 4
                p.drawLine(QPointF(11 + 6 * math.cos(a), 11 + 6 * math.sin(a)),
                           QPointF(11 + 9 * math.cos(a), 11 + 9 * math.sin(a)))
            p.drawEllipse(QPointF(11, 11), 6, 6)
            p.drawEllipse(QPointF(11, 11), 2.2, 2.2)
        elif name == "copy":
            p.drawRect(QRectF(3, 3, 11, 11)); p.drawRect(QRectF(8, 8, 11, 11))
        elif name == "cut":
            p.drawEllipse(QRectF(3, 13, 6, 6)); p.drawEllipse(QRectF(13, 13, 6, 6))
            p.drawLine(QPointF(8, 14), QPointF(16, 3)); p.drawLine(QPointF(14, 14), QPointF(6, 3))
        elif name == "paste":
            p.drawRect(QRectF(4, 5, 14, 15)); p.setBrush(color); p.drawRect(QRectF(8, 3, 6, 4))
        elif name == "undo":
            p.drawArc(QRectF(5, 6, 13, 12), 90 * 16, -200 * 16); poly(p, [(3, 9), (8, 5), (8, 12)])
        elif name == "redo":
            p.drawArc(QRectF(4, 6, 13, 12), 90 * 16, 200 * 16); poly(p, [(19, 9), (14, 5), (14, 12)])
        else:
            p.drawRect(QRectF(5, 5, 12, 12))

    return _icon(d, s)


def app_icon() -> QIcon:
    pm = QPixmap(256, 256)
    pm.fill(QColor(PAPER))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(QRectF(0, 0, 256, 256), QColor(INK))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(RED))
    p.drawEllipse(QRectF(130, 24, 100, 100))
    p.setBrush(QColor(YELLOW))
    p.drawRect(QRectF(24, 150, 80, 80))
    p.setPen(QColor(PAPER))
    f = ui_font(64, True)
    p.setFont(f)
    p.drawText(QRectF(0, 110, 248, 140), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, "N40")
    p.end()
    return QIcon(pm)
