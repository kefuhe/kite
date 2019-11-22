from collections import OrderedDict

from PyQt5 import QtCore, QtGui
import pyqtgraph as pg
import pyqtgraph.parametertree.parameterTypes as pTypes

from kite.qt_utils import SliderWidgetParameterItem
from kite.quadtree import QuadtreeConfig

from .base import KiteView, KitePlot, KiteParameterGroup


class KiteQuadtree(KiteView):
    title = 'Scene.quadtree'

    def __init__(self, spool):
        model = spool.model
        self.main_widget = KiteQuadtreePlot(model)
        self.tools = {}

        self.param_quadtree = KiteParamQuadtree(
            model,
            self.main_widget,
            expanded=True)
        self.parameters = [self.param_quadtree]

        model.sigSceneModelChanged.connect(self.modelChanged)

        KiteView.__init__(self)

    def modelChanged(self):
        self.main_widget.update()
        self.main_widget.transFromFrame()
        self.main_widget.updateFocalPoints()

        self.param_quadtree.updateValues()
        self.param_quadtree.onConfigUpdate()
        self.param_quadtree.updateEpsilonLimits()


class QQuadLeaf(QtCore.QRectF):

    leaf_outline = pg.mkPen((255, 255, 255, 100), width=1)
    leaf_fill = pg.mkBrush(0, 0, 0, 0)

    def __init__(self, leaf):
        self.id = leaf.id
        QtCore.QRectF.__init__(
            self,
            QtCore.QPointF(leaf.llE, leaf.llN + leaf.sizeN),
            QtCore.QPointF(leaf.llE + leaf.sizeE, leaf.llN))

    def getRectItem(self):
        item = QtGui.QGraphicsRectItem(self)
        item.setPen(self.leaf_outline)
        item.setBrush(self.leaf_fill)
        item.setZValue(1e8)
        return item


class QQuadSelectedLeaf(QQuadLeaf):
    leaf_outline = pg.mkPen((202, 60, 60), width=1)
    leaf_fill = pg.mkBrush(202, 60, 60, 120)


class KiteQuadtreePlot(KitePlot):
    def __init__(self, model):

        self.components_available = {
            'mean':
            ['Node.mean displacement',
             lambda sp: sp.quadtree.leaf_matrix_means],
            'median':
            ['Node.median displacement',
             lambda sp: sp.quadtree.leaf_matrix_medians],
            'weight':
            ['Node.weight covariance',
             lambda sp: sp.quadtree.leaf_matrix_weights],
        }

        self._component = 'median'

        KitePlot.__init__(self, model=model, los_arrow=True)

        focalpoint_color = (78, 255, 0)
        focalpoint_outline_color = (0, 0, 0)
        self.focal_points = pg.ScatterPlotItem(
            size=3.5,
            pen=pg.mkPen(
                focalpoint_outline_color,
                width=.3),
            brush=pg.mkBrush(focalpoint_color),
            antialias=True)

        self.setMenuEnabled(True)

        self.highlighted_leaves = []
        self.selected_leaves = []
        self.outlined_leaves = []

        self.eraseBox = QtGui.QGraphicsRectItem(0, 0, 1, 1)
        self.eraseBox.setPen(
            pg.mkPen(
                (202, 60, 60),
                width=1,
                style=QtCore.Qt.DotLine))
        self.eraseBox.setBrush(pg.mkBrush(202, 60, 60, 40))
        self.eraseBox.setZValue(1e9)
        self.eraseBox.hide()
        self.addItem(self.eraseBox, ignoreBounds=True)

        self.vb = self.getViewBox()
        self.vb.mouseDragEvent = self.mouseDragEvent
        self.vb.keyPressEvent = self.blacklistSelectedLeaves

        self.addItem(self.focal_points)

        def covarianceChanged():
            if self._component == 'weight':
                self.update()

        self.model.sigQuadtreeChanged.connect(self.unselectLeaves)
        self.model.sigQuadtreeChanged.connect(self.update)
        self.model.sigQuadtreeChanged.connect(self.updateFocalPoints)
        self.model.sigQuadtreeChanged.connect(self.updateLeavesOutline)
        self.model.sigCovarianceChanged.connect(covarianceChanged)

        # self.model.sigFrameChanged.connect(self.transFromFrame)
        # self.model.sigFrameChanged.connect(self.transFromFrameScatter)

        self.updateLeavesOutline()
        self.updateFocalPoints()

    def transFromFrameScatter(self):
        self.focal_points.resetTransform()
        self.focal_points.scale(
            self.model.frame.dE, self.model.frame.dN)

    def updateFocalPoints(self):
        if self.model.quadtree.leaf_focal_points.size == 0:
            self.focal_points.clear()
        else:
            self.focal_points.setData(
                pos=self.model.quadtree.leaf_focal_points,
                pxMode=True)

    def updateEraseBox(self, p1, p2):
        r = QtCore.QRectF(p1, p2)
        r = self.vb.childGroup.mapRectFromParent(r)
        self.eraseBox.r = r
        self.eraseBox.setPos(r.topLeft())
        self.eraseBox.resetTransform()
        self.eraseBox.scale(r.width(), r.height())
        self.eraseBox.show()

    @QtCore.pyqtSlot(object)
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() & (QtCore.Qt.LeftButton | QtCore.Qt.MidButton):
            return pg.ViewBox.mouseDragEvent(self.vb, ev, axis)

        ev.accept()
        if ev.isFinish():
            self.eraseBox.hide()
            self.selectLeaves()
        else:
            self.updateEraseBox(ev.buttonDownPos(), ev.pos())

    def getQLeaves(self, cls):
        return [cls(lf) for lf in self.model.quadtree.leaves]

    @QtCore.pyqtSlot()
    def selectLeaves(self):
        self.unselectLeaves()

        self.selected_leaves = [lf for lf in self.getQLeaves(QQuadSelectedLeaf)
                                if self.eraseBox.r.contains(lf)]
        for lf in self.selected_leaves:
            leaf_item = lf.getRectItem()
            leaf_item.setZValue(1e9)
            leaf_item.setToolTip('Press Del to remove')

            self.highlighted_leaves.append(leaf_item)
            self.addItem(leaf_item)

    @QtCore.pyqtSlot()
    def unselectLeaves(self):
        if self.selected_leaves:
            for lf in self.highlighted_leaves:
                self.removeItem(lf)
            del self.highlighted_leaves
            del self.selected_leaves
            self.highlighted_leaves = []
            self.selected_leaves = []

    @QtCore.pyqtSlot(object)
    def blacklistSelectedLeaves(self, ev):
        if ev.key() == QtCore.Qt.Key_Delete:
            self.model.quadtree.blacklistLeaves(
                lf.id for lf in self.selected_leaves)

    @QtCore.pyqtSlot()
    def updateLeavesOutline(self):
        for lf in self.outlined_leaves:
            self.removeItem(lf)
        del self.outlined_leaves
        self.outlined_leaves = []

        for lf in self.getQLeaves(QQuadLeaf):
            leaf_item = lf.getRectItem()
            self.outlined_leaves.append(leaf_item)
            self.addItem(leaf_item)


class KiteParamQuadtree(KiteParameterGroup):
    sigEpsilon = QtCore.pyqtSignal(float)
    sigNanFraction = QtCore.pyqtSignal(float)
    sigTileMaximum = QtCore.pyqtSignal(float)
    sigTileMinimum = QtCore.pyqtSignal(float)

    def __init__(self, model, plot, *args, **kwargs):
        self.plot = plot
        self.sig_guard = True
        self.sp = model

        kwargs['type'] = 'group'
        kwargs['name'] = 'Scene.quadtree'
        self.parameters = OrderedDict(
            [('nleaves', None),
             ('reduction_rms', None),
             ('reduction_efficiency', None),
             ('epsilon_min', None),
             ('nnodes', None),
             ])

        KiteParameterGroup.__init__(
            self,
            model=model,
            model_attr='quadtree',
            **kwargs)

        model.sigQuadtreeConfigChanged.connect(self.onConfigUpdate)
        model.sigQuadtreeChanged.connect(self.updateValues)

        self.sigEpsilon.connect(model.qtproxy.setEpsilon)
        self.sigNanFraction.connect(model.qtproxy.setNanFraction)
        self.sigTileMaximum.connect(model.qtproxy.setTileMaximum)
        self.sigTileMinimum.connect(model.qtproxy.setTileMinimum)

        def updateGuard(func):
            def wrapper(*args, **kwargs):
                if not self.sig_guard:
                    func()
            return wrapper

        # Epsilon control
        @updateGuard
        def updateEpsilon():
            self.sigEpsilon.emit(self.epsilon.value())

        p = {
            'name': 'epsilon',
            'type': 'float',
            'value': model.quadtree.epsilon,
            'default': model.quadtree._epsilon_init,
            'step': round((model.quadtree.epsilon -
                           model.quadtree.epsilon_min)*.1, 3),
            'limits': (model.quadtree.epsilon_min,
                       3*model.quadtree._epsilon_init),
            'editable': True,
            'decimals': 3,
            'tip': QuadtreeConfig.epsilon.help
        }
        self.epsilon = pTypes.SimpleParameter(**p)
        self.epsilon.itemClass = SliderWidgetParameterItem
        self.epsilon.sigValueChanged.connect(updateEpsilon)

        # Epsilon control
        @updateGuard
        def updateNanFrac():
            self.sigNanFraction.emit(self.nan_allowed.value())

        p = {'name': 'nan_allowed',
             'type': 'float',
             'value': model.quadtree.nan_allowed,
             'default': QuadtreeConfig.nan_allowed.default(),
             'step': 0.05,
             'limits': (0., 1.),
             'editable': True,
             'decimals': 2,
             'tip': QuadtreeConfig.nan_allowed.help
             }
        self.nan_allowed = pTypes.SimpleParameter(**p)
        self.nan_allowed.itemClass = SliderWidgetParameterItem
        self.nan_allowed.sigValueChanged.connect(updateNanFrac)

        # Tile size controls
        @updateGuard
        def updateTileSizeMin():
            self.sigTileMinimum.emit(self.tile_size_min.value())

        frame = model.frame
        max_px = max(frame.shape)
        max_d = max(frame.dE, frame.dN)
        limits = (max_d * 5, max_d * (max_px / 4))
        p = {'name': 'tile_size_min',
             'type': 'float',
             'value': model.quadtree.tile_size_min,
             'default': QuadtreeConfig.tile_size_min.default(),
             'limits': limits,
             'step': 250,
             'editable': True,
             'suffix': ' m' if frame.isMeter() else ' deg',
             'decimals': 0 if frame.isMeter() else 3,
             'tip': QuadtreeConfig.tile_size_min.help
             }
        self.tile_size_min = pTypes.SimpleParameter(**p)
        self.tile_size_min.itemClass = SliderWidgetParameterItem

        @updateGuard
        def updateTileSizeMax():
            self.sigTileMaximum.emit(self.tile_size_max.value())

        p.update({'name': 'tile_size_max',
                  'value': model.quadtree.tile_size_max,
                  'default': QuadtreeConfig.tile_size_max.default(),
                  'tip': QuadtreeConfig.tile_size_max.help
                  })
        self.tile_size_max = pTypes.SimpleParameter(**p)
        self.tile_size_max.itemClass = SliderWidgetParameterItem

        self.tile_size_min.sigValueChanged.connect(updateTileSizeMin)
        self.tile_size_max.sigValueChanged.connect(updateTileSizeMax)

        # Component control
        def changeComponent():
            self.plot.component = self.components.value()

        p = {'name': 'display',
             'values': {
                'QuadNode.mean': 'mean',
                'QuadNode.median': 'median',
                'QuadNode.weight': 'weight',
             },
             'value': 'mean',
             'tip': 'Change displayed component'
             }
        self.components = pTypes.ListParameter(**p)
        self.components.sigValueChanged.connect(changeComponent)

        def changeCorrection():
            model.quadtree.setCorrection(correction_method.value())
            self.updateEpsilonLimits()

        p = {'name': 'setCorrection',
             'values': {
                'Mean (Jonsson, 2002)': 'mean',
                'Median (Jonsson, 2002)': 'median',
                'Bilinear (Jonsson, 2002)': 'bilinear',
                'SD (Jonsson, 2002)': 'std',
                 },
             'value': model.quadtree.config.correction,
             'tip': QuadtreeConfig.correction.help
             }
        correction_method = pTypes.ListParameter(**p)
        correction_method.sigValueChanged.connect(changeCorrection)

        self.sig_guard = False
        self.pushChild(correction_method)
        self.pushChild(self.tile_size_max)
        self.pushChild(self.tile_size_min)
        self.pushChild(self.nan_allowed)
        self.pushChild(self.epsilon)
        self.pushChild(self.components)

    def onConfigUpdate(self):
        self.sig_guard = True
        for p in ['epsilon', 'nan_allowed',
                  'tile_size_min', 'tile_size_max']:
            param = getattr(self, p)
            param.setValue(getattr(self.sp.quadtree, p))
        self.sig_guard = False

    def updateEpsilonLimits(self):
        self.epsilon.setLimits(
            (self.sp.quadtree.epsilon_min, 3*self.sp.quadtree._epsilon_init))
