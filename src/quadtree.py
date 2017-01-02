import numpy as num
import time
from pyrocko import guts

from .meta import Subject, property_cached, derampMatrix


class QuadNode(object):
    ''' A node (or *tile*) in held by :class:`~kite.Quadtree`. Each node in the
    tree hold a back reference to the quadtree and scene to access

    :param llr: Lower left corner row in :attr:`kite.Scene.displacement`
        matrix.
    :type llr: int
    :param llc: Lower left corner column in :attr:`kite.Scene.displacement`
        matrix.
    :type llc: int
    :param length: Length of node in from ``llr, llc`` in both dimensions
    :type length: int
    :param id: Unique id of node
    :type id: str
    :param children: Node's children
    :type children: List of :class:`~kite.quadtree.QuadNode`
    '''

    def __init__(self, quadtree, llr, llc, length):
        self.children = None
        self.llr = int(llr)
        self.llc = int(llc)
        self.length = int(length)
        self._slice_rows = slice(self.llr, self.llr + self.length)
        self._slice_cols = slice(self.llc, self.llc + self.length)
        self.id = 'node_%d-%d_%d' % (self.llr, self.llc, self.length)

        self.quadtree = quadtree
        self.scene = quadtree.scene

    @property_cached
    def nan_fraction(self):
        ''' Fraction of NaN values within the tile
        :type: float
        '''
        return float(num.sum(self.displacement_mask)) / \
            self.displacement.size

    @property_cached
    def mean(self):
        ''' Mean displacement
        :type: float
        '''
        return num.nanmean(self.displacement)

    @property_cached
    def median(self):
        ''' Median displacement
        :type: float
        '''
        return num.nanmedian(self.displacement)

    @property_cached
    def std(self):
        ''' Standard deviation of displacement
        :type: float
        '''
        return num.nanstd(self.displacement)

    @property_cached
    def var(self):
        ''' Variance of displacement
        :type: float
        '''
        return num.nanvar(self.displacement)

    @property_cached
    def corr_median(self):
        ''' Standard deviation of node's displacement corrected for median
        :type: float
        '''
        return num.nanstd(self.displacement - self.median)

    @property_cached
    def corr_mean(self):
        ''' Standard deviation of node's displacement corrected for mean
        :type: float
        '''
        return num.nanstd(self.displacement - self.mean)

    @property_cached
    def corr_bilinear(self):
        ''' Standard deviation of node's displacement corrected for bilinear
            trend (2D)
        :type: float
        '''
        return num.nanstd(derampMatrix(self.displacement))

    @property
    def weight(self):
        '''
        :getter: Absolute weight derived from :class:`kite.Covariance`
         - works on tree leafs only.
        :type: float
        '''
        return self.quadtree.scene.covariance.getLeafWeight(self)

    @property_cached
    def focal_point(self):
        ''' Node focal point in local coordinates respecting NaN values
        :type: tuple, float - (easting, northing)
        '''
        E = num.median(self.gridE.compressed())
        N = num.median(self.gridN.compressed())
        return E, N

    @property_cached
    def displacement(self):
        ''' Displacement array, slice from :attr:`kite.Scene.displacement`
        :type: :class:`numpy.array`
        '''
        return self.scene.displacement[self._slice_rows, self._slice_cols]

    @property_cached
    def displacement_masked(self):
        ''' Masked displacement,
            see :attr:`~kite.quadtree.QuadNode.displacement`
        :type: :class:`numpy.array`
        '''
        return num.ma.masked_array(self.displacement,
                                   self.displacement_mask,
                                   fill_value=num.nan)

    @property_cached
    def displacement_mask(self):
        ''' Displacement nan mask of
            :attr:`~kite.quadtree.QuadNode.displacement`
        :type: :class:`numpy.array`, dtype :class:`numpy.bool`

        .. todo ::

            Faster to slice Scene.displacement_mask?
        '''
        return num.isnan(self.displacement)

    @property_cached
    def phi(self):
        ''' Median Phi angle, see :class:`~kite.Scene`.
        :type: float
        '''
        phi = self.scene.phi[self._slice_rows, self._slice_cols]
        return num.median(phi[~self.displacement_mask])

    @property_cached
    def theta(self):
        ''' Median Theta angle, see :class:`~kite.Scene`.
        :type: float
        '''
        theta = self.scene.theta[self._slice_rows, self._slice_cols]
        return num.median(theta[~self.displacement_mask])

    @property_cached
    def gridE(self):
        ''' Grid holding local east coordinates,
            see :attr:`kite.scene.Frame.gridE`.
        :type: :class:`numpy.array`
        '''
        return self.scene.frame.gridE[self._slice_rows, self._slice_cols]

    @property_cached
    def gridN(self):
        ''' Grid holding local north coordinates,
            see :attr:`kite.scene.Frame.gridN`.
        :type: :class:`numpy.array`
        '''
        return self.scene.frame.gridN[self._slice_rows, self._slice_cols]

    @property
    def llE(self):
        '''
        :getter: Lower left east coordinate in local coordinates (*meter*).
        :type: float
        '''
        return self.scene.frame.E[self.llc]

    @property
    def llN(self):
        '''
        :getter: Lower left north coordinate in local coordinates (*meter*).
        :type: float
        '''
        return self.scene.frame.N[self.llr]

    @property_cached
    def sizeE(self):
        '''
        :getter: Size in eastern direction in *meters*.
        :type: float
        '''
        sizeE = self.length * self.scene.frame.dE
        if (self.llE + sizeE) > self.scene.frame.E.max():
            sizeE = self.scene.frame.E.max() - self.llE
        return sizeE

    @property_cached
    def sizeN(self):
        '''
        :getter: Size in northern direction in *meters*.
        :type: float
        '''
        sizeN = self.length * self.scene.frame.dN
        if (self.llN + sizeN) > self.scene.frame.N.max():
            sizeN = self.scene.frame.N.max() - self.llN
        return sizeN

    def iterChildren(self):
        ''' Iterator over the all children.

        :yields: Children of it's own.
        :type: :class:`~kite.quadtree.QuadNode`
        '''
        yield self
        if self.children is not None:
            for c in self.children:
                for rc in c.iterChildren():
                    yield rc

    def iterLeafs(self):
        ''' Iterator over the leafs, evaluating parameters from
        :class:`~kite.Quadtree` instance.

        :yields: Leafs fullfilling the tree's parameters.
        :type: :class:`~kite.quadtree.QuadNode`
        '''
        if (self.quadtree._corr_func(self) < self.quadtree.epsilon and
            not self.length > self.quadtree._tile_size_lim_px[1])\
           or self.children is None:
            yield self
        elif self.children[0].length < self.quadtree._tile_size_lim_px[0]:
            yield self
        else:
            for c in self.children:
                for q in c.iterLeafs():
                    yield q

    def _iterSplitNode(self):
        if self.length == 1:
            yield None
        for _nr, _nc in ((0, 0), (0, 1), (1, 0), (1, 1)):
            n = QuadNode(self.quadtree,
                         self.llr + self.length / 2 * _nr,
                         self.llc + self.length / 2 * _nc,
                         self.length / 2)
            if n.displacement.size == 0 or num.all(n.displacement_mask):
                n = None
                continue
            yield n

    def createTree(self):
        ''' Create the tree from a set of basenodes, ignited by
        :class:`~kite.Quadtree` instance. Evaluates :class:`~kite.Quadtree`
        correction method and :attr:`~kite.Quadtree.epsilon_min`.
        '''
        if (self.quadtree._corr_func(self) > self.quadtree.epsilon_min
            or self.length >= 64)\
           and not self.length < 16:
            # self.length > .1 * max(self.quadtree._data.shape): !! Expensive
            self.children = [c for c in self._iterSplitNode()]
            for c in self.children:
                c.createTree()
        else:
            self.children = None


class QuadtreeConfig(guts.Object):
    ''' Quadtree configuration object holding essential parameters used to
    reconstruct a particular tree
    '''
    correction = guts.StringChoice.T(
        choices=['mean', 'median', 'bilinear', 'std'],
        default='median',
        help='Node correction for splitting, available methods '
             ' ``[\'mean\', \'median\', \'bilinear\', \'std\']``')
    epsilon = guts.Float.T(
        optional=True,
        help='Threshold for node splitting, measure for '
             'quadtree nodes\' variance')
    nan_allowed = guts.Float.T(
        default=0.9,
        help='Allowed NaN fraction per tile')
    tile_size_min = guts.Float.T(
        default=250.,
        help='Minimum allowed tile size in *meter*')
    tile_size_max = guts.Float.T(
        default=25e3,
        help='Maximum allowed tile size in *meter*')


class Quadtree(object):
    """Quadtree for simplifying InSAR displacement data held in
    :class:`kite.scene.Scene`

    Post-earthquake InSAR displacement scenes can hold a vast amount of data,
    which is unsuiteable for use with modelling code. By simplifying the data
    systematicallc through a parametrized quadtree we can reduce the dataset to
    significant displacements and have high-resolution where it matters and
    lower resolution at regions with less or constant deformation.

    The standard deviation from :attr:`kite.quadtree.QuadNode.displacement`
    is evaluated against different corrections:

        * ``mean``: Mean is substracted
        * ``median``: Median is substracted
        * ``bilinear``: A 2D detrend is applied to the node
        * ``std``:  Pure standard deviation without correction

    set through :func:`~kite.Quadtree.setCorrection`. If the standard deviation
    exceeds :attr:`~kite.Quadtree.epsilon` the node is split.

    Controlling attributes are:

        * :attr:`~kite.Quadtree.epsilon`, RMS threshold
        * :attr:`~kite.Quadtree.nan_fraction`, allowed :attr:`numpy.nan` in
          node
        * :attr:`~kite.Quadtree.tile_size_max`, maximum node size in *meter*
        * :attr:`~kite.Quadtree.tile_size_min`, minimum node size in *meter*

    :attr:`~kite.Quadtree.leafs` hold the current tree's
    :class:`~kite.quadtree.QuadNode` 's. The leafs can also be exported in a
    *CSV* format through :func:`~kite.Quadtree.export`.
    """
    evChanged = Subject()
    evConfigChanged = Subject()

    _corrections = {
        'mean':
        ['Std around mean', lambda n: n.corr_mean],
        'median':
        ['Std around median', lambda n: n.corr_median],
        'bilinear':
        ['Std around bilinear detrended node', lambda n: n.corr_bilinear],
        'std':
        ['Standard deviation (std)', lambda n: n.std],

    }
    _norm_methods = {
        'mean': lambda n: n.mean,
        'median': lambda n: n.median,
        'weight': lambda n: n.weight,
    }

    def __init__(self, scene, config=QuadtreeConfig()):
        self._leafs = None
        self.scene = scene
        self.displacement = self.scene.displacement
        self.frame = self.scene.frame

        # Cached matrizes
        self._leaf_matrix_means = num.empty_like(self.displacement)
        self._leaf_matrix_medians = num.empty_like(self.displacement)
        self._leaf_matrix_weights = num.empty_like(self.displacement)

        self._log = scene._log.getChild('Quadtree')
        self.setConfig(config)

        self.scene.evConfigChanged.subscribe(self.setConfig)

    def setConfig(self, config=None):
        """ Sets and updated the config of the instance

        :param config: New config instance, defaults to configuration provided
                       by parent :class:`~kite.Scene`
        :type config: :class:`~kite.covariance.QuadtreeConfig`, optional
        """
        if config is None:
            config = self.scene.config.quadtree
        self.config = config
        self.setCorrection(self.config.correction)

        self.evConfigChanged.notify()

    def setCorrection(self, correction='mean'):
        """ Set correction method calculating the standard deviation of
        instances :class:`~kite.quadtree.QuadNode` s

        The standard deviation from :attr:`kite.quadtree.QuadNode.displacement`
        is evaluated against different corrections:

        * ``mean``: Mean is substracted
        * ``median``: Median is substracted
        * ``bilinear``: A 2D detrend is applied to the node
        * ``std``:  Pure standard deviation without correction

        :param correction: Choose from methods
            ``mean_std, median_std, bilinear_std, std``
        :type correction: str
        :raises: AttributeError
        """
        if correction not in self._corrections.keys():
            raise AttributeError('Method %s not in %s'
                                 % (correction, self._corrections))
        self._log.debug('Changing to split method \'%s\'' % correction)

        self.config.correction = correction
        self._corr_func = self._corrections[correction][1]

        # Clearing cached properties through None
        self.leafs = None
        self.nodes = None
        self.epsilon_min = None
        self._epsilon_init = None
        self.epsilon = self.config.epsilon or self._epsilon_init

        self._initTree()
        self.evChanged.notify()

    def _initTree(self):
        t0 = time.time()
        for b in self._base_nodes:
            b.createTree()

        self._log.debug(
            'Tree created, %d nodes [%0.8f s]' %
            (self.nnodes, time.time() - t0))

    @property
    def epsilon(self):
        """ Epsilon threshold where :class:`~kite.quadtree.QuadNode` is split.
        Synonym could be ``std_max`` or ``std_split``.

        :setter: Sets the epsilon/RMS threshold
        :getter: Returns the current epsilon
        :type: float
        """
        return self.config.epsilon

    @epsilon.setter
    def epsilon(self, value):
        value = float(value)
        if self.config.epsilon == value:
            return
        if value < self.epsilon_min:
            self._log.warning(
                'Epsilon is out of bounds [%0.6f], epsilon_min %0.6f' %
                (value, self.epsilon_min))
            return
        self.leafs = None
        self.config.epsilon = value

        self.evChanged.notify()
        return

    @property_cached
    def _epsilon_init(self):
        ''' Initial epsilon for virgin tree creation '''
        return num.nanstd(self.displacement)

    @property_cached
    def epsilon_min(self):
        """ Lowest allowed epsilon
        :type: float
        """
        return self._epsilon_init * .2

    @property
    def nan_allowed(self):
        """ Fraction of allowed ``NaN`` values allwed in quadtree leafs, if
        value is exceeded the leaf is kicked out.

        :setter: Fraction  ``0. <= fraction <= 1``.
        :type: float
        """
        return self.config.nan_allowed

    @nan_allowed.setter
    def nan_allowed(self, value):
        if (value > 1. or value <= 0.):
            self._log.warning('NaN fraction must be 0. < nan_allowed <= 1.')
            return

        self.leafs = None
        self.config.nan_allowed = value
        self.evChanged.notify()

    @property
    def tile_size_min(self):
        """ Minimum allowed tile size in *meter*.
        Measured along long edge ``(max(dE, dN))``

        :getter: Returns the minimum allowed tile size
        :setter: Sets the minimum threshold
        :type: float
        """
        return self.config.tile_size_min

    @tile_size_min.setter
    def tile_size_min(self, value):
        if value > self.tile_size_max:
            self._log.warning('tile_size_min > tile_size_max is required')
            return
        self.config.tile_size_min = value
        self._tileSizeChanged()

    @property
    def tile_size_max(self):
        """ Maximum allowed tile size in *meter*.
        Measured along long edge ``(max(dE, dN))``

        :getter: Returns the maximum allowed tile size
        :setter: Sets the maximum threshold
        :type: float
        """
        return self.config.tile_size_max

    @tile_size_max.setter
    def tile_size_max(self, value):
        if value < self.tile_size_min:
            self._log.warning('tile_size_min > tile_size_max is required')
            return
        self.config.tile_size_max = value
        self._tileSizeChanged()

    def _tileSizeChanged(self):
        self._tile_size_lim_px = None
        self.leafs = None
        self.evChanged.notify()

    @property_cached
    def _tile_size_lim_px(self):
        dpx = self.scene.frame.dE\
            if self.scene.frame.dE > self.scene.frame.dN\
            else self.scene.frame.dN
        return (int(self.tile_size_min / dpx),
                int(self.tile_size_max / dpx))

    @property_cached
    def nodes(self):
        """ All nodes of the tree

        :getter: Get the list of nodes
        :type: list
        """
        return [n for b in self._base_nodes for n in b.iterChildren()]

    @property
    def nnodes(self):
        """
        :getter: Number of nodes of the built tree.
        :type: int
        """
        return len(self.nodes)

    @property_cached
    def leafs(self):
        """
        :getter: List of leafs for current configuration.
        :type: (list or :class:`~kite.quadtree.QuadNode` s)
        """
        t0 = time.time()
        leafs = []
        for b in self._base_nodes:
            leafs.extend([l for l in b.iterLeafs()
                          if l.nan_fraction < self.nan_allowed])
        self._log.debug(
            'Gathering leafs for epsilon %.4f (nleafs=%d) [%0.8f s]' %
            (self.epsilon, len(leafs), time.time() - t0))
        return leafs

    @property
    def nleafs(self):
        """
        :getter: Number of leafs for current parametrisation.
        :type: int
        """
        return len(self.leafs)

    @property
    def leaf_means(self):
        """
        :getter: Leaf mean displacements from
            :attr:`kite.quadtree.QuadNode.mean`.
        :type: :class:`numpy.ndarray`, size ``N``.
        """
        return num.array([l.mean for l in self.leafs])

    @property
    def leaf_medians(self):
        """
        :getter: Leaf median displacements from
            :attr:`kite.quadtree.QuadNode.median`.
        :type: :class:`numpy.ndarray`, size ``N``.
        """
        return num.array([l.median for l in self.leafs])

    @property
    def _leaf_focal_points(self):
        return num.array([l._focal_point for l in self.leafs])

    @property
    def leaf_focal_points(self):
        """
        :getter: Leaf focal points in local coordinates.
        :type: :class:`numpy.ndarray`, size ``(2,N)``
        """
        return num.array([l.focal_point for l in self.leafs])

    @property
    def leaf_matrix_means(self):
        """
        :getter: Leaf mean displacements casted to
            :attr:`kite.Scene.displacement`.
        :type: :class:`numpy.ndarray`, size ``(N,M)``
        """
        return self._getLeafsNormMatrix(self._leaf_matrix_means,
                                        method='mean')

    @property
    def leaf_matrix_medians(self):
        """
        :getter: Leaf median displacements casted to
            :attr:`kite.Scene.displacement`.
        :type: :class:`numpy.ndarray`, size ``(N,M)``
        """
        return self._getLeafsNormMatrix(self._leaf_matrix_medians,
                                        method='median')

    @property
    def leaf_matrix_weights(self):
        """
        :getter: Leaf weights casted to :attr:`kite.Scene.displacement`.
        :type: :class:`numpy.ndarray`, size ``(N,M)``
        """
        return self._getLeafsNormMatrix(self._leaf_matrix_weights,
                                        method='weight')

    def _getLeafsNormMatrix(self, array, method='median'):
        if method not in self._norm_methods.keys():
            raise AttributeError(
                'Method %s is not in %s' %
                (method, self._norm_methods.keys()))
        t0 = time.time()  # noqa
        array.fill(num.nan)
        for l in self.leafs:
            array[l._slice_rows, l._slice_cols] = \
                self._norm_methods[method](l)
        array[self.scene.displacement_mask] = num.nan
        # print time.time()-t0, method
        return array

    @property
    def reduction_efficiency(self):
        ''' This is measure for the reduction of the scene's full resolution
        over the quadtree.

        :getter: Quadtree efficiency as :math:`N_{full} / N_{leafs}`
        :type: float
        '''
        return (self.scene.rows * self.scene.cols) / self.nleafs

    @property
    def reduction_rms(self):
        ''' The RMS error is defined between
        :attr:`~kite.Quadtree.leaf_matrix_means` and
        :attr:`kite.Scene.displacement`.

        :getter: The reduction RMS error
        :type: float
        '''
        return num.sqrt(num.nanmean((self.scene.displacement -
                                     self.leaf_matrix_means)**2))

    @property_cached
    def _base_nodes(self):
        self._base_nodes = []
        init_length = num.power(
            2, num.ceil(num.log(num.min(self.displacement.shape))
                        / num.log(2)))
        nx, ny = num.ceil(num.array(self.displacement.shape) / init_length)
        self._log.debug('Creating %d base nodes' % (nx * ny))

        for ir in xrange(int(nx)):
            for ic in xrange(int(ny)):
                llr = ir * init_length
                llc = ic * init_length
                self._base_nodes.append(QuadNode(self, llr, llc, init_length))

        if len(self._base_nodes) == 0:
            raise AssertionError('Could not init base nodes.')
        return self._base_nodes

    @property_cached
    def plot(self):
        """ Simple `matplotlib` illustration of the quadtree

        :type: :attr:`Quadtree.leaf_matrix_means`.
        """
        from kite.plot2d import QuadtreePlot
        return QuadtreePlot(self)

    def getStaticTarget(self):
        """Not Implemented
        """
        raise NotImplementedError

    def export(self, filename):
        """ Exports the current quadtree leafs to ``filename`` in a
        *CSV* format

        The formatting is::

            # node_id, focal_point_E, focal_point_N, theta, phi, \
mean_displacement, median_displacement, absolute_weight

        :param filename: export to path
        :type filename: string
        """
        self._log.debug('Exporting Quadtree.leafs to %s' % filename)
        with open(filename, mode='w') as f:
            f.write(
                '# node_id, focal_point_E, focal_point_N, theta, phi, '
                'mean_displacement, median_displacement, absolute_weight\n')
            for l in self.leafs:
                f.write(
                    '{l.id}, {l.focal_point[0]}, {l.focal_point[1]}, '
                    '{l.theta}, {l.phi}, '
                    '{l.mean}, {l.median}, {l.weight}\n'.format(l=l))


__all__ = ['Quadtree', 'QuadtreeConfig']


if __name__ == '__main__':
    from kite.scene import SceneSynTest
    sc = SceneSynTest.createGauss(2000, 2000)

    for e in num.linspace(0.1, .00005, num=30):
        sc.quadtree.epsilon = e
    # qp = Plot2DQuadTree(qt, cmap='spectral')
    # qp.plot()
