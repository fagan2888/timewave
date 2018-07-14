from math import sqrt
from random import Random

import numpy as np

from scipy.stats import norm
from scipy.linalg import expm, logm

from base import StochasticProcess

EPS = 1e-7


class FiniteStateMarkovChain(StochasticProcess):
    @property
    def transition(self):
        return self._transition_matrix.tolist()

    @property
    def r_squared(self):
        return self._r_squared

    @classmethod
    def random(cls, d=5):
        # pick random vector and matrix with positive values
        s = np.random.random((1, d))
        t = np.random.random((d, d))

        # turn them into stochastic ones
        s = s / s.sum(1)
        t = t / t.sum(1).reshape((d, 1))

        # build process instance
        return cls(transition=t.tolist(), r_squared=1., start=list(s.flat))

    def __init__(self, transition=None, r_squared=1., start=None):
        """

        :param list transition: stochastic matrix of transition probabilities,
                                i.e. np.ndarray with shape=2 and sum of each line equal to 1
                                (optional) default: identity matrix
        :param float r_squared: square of systematic correlation in factor simulation
                                (optional) default: 1.
        :param list start: initial state distribution, i.e. np.ndarray with shape=1 or list, adding up to 1,
                           (optional) default: unique distribution

        """

        # if any argument is missing use defaults
        if transition is None and start is None:
            dim = 2
        else:
            dim = len(transition) if start is None else len(start)

        start = (np.ones(dim) / dim).tolist() if start is None else list(start)
        transition = np.identity(dim) if transition is None else transition
        self._transition_matrix = np.matrix(transition, float)

        self._r_squared = r_squared
        self._idiosyncratic_random = Random()
        super(FiniteStateMarkovChain, self).__init__(start)

        # validate argument shapes in shapes and sum for being stochastic
        assert abs(self._transition_matrix.sum(1) - 1.).sum() < EPS, \
            'transition probabilities do not from distribution.\n' + str(self._transition_matrix)
        assert abs(sum(self.start) - 1.) < EPS, \
            'start does not from distribution.\n' + str(self.start)
        assert (len(self.start), len(self.start)) == self._transition_matrix.shape, \
            'dimension of transition and start argument must meet.\n' \
            + str(self.start) + '\n' + str(self._transition_matrix)

    def __len__(self):
        return 1

    def __str__(self):
        return self.__class__.__name__ + '(dim=%d)' % len(self.start)

    def _m_pow(self, t, s=0.):
        return self._transition_matrix ** int(t - s)

    def evolve(self, x, s, e, q):
        q = sqrt(self._r_squared) * q + sqrt(1.-self._r_squared) * self._idiosyncratic_random.gauss(0., 1.)
        p = norm.cdf(q)
        m = self._m_pow(e, s)
        mm = np.greater(m.cumsum(1), p) * 1.
        mm[0:, 1:] -= mm[0:, :-1]
        return list(np.asarray(x, float).dot(mm).flat)

    def mean(self, t):
        return self._underlying_mean(t)

    def variance(self, t):
        return list(np.diag(self._underlying_covariance(t)).flat)

    def _underlying_mean(self, t):
        s = np.asarray(self.start, float)
        m = self._m_pow(t)
        return list(s.dot(m).flat)

    def _underlying_covariance(self, t):
        def _e_xy(prop_x, cum_prop_x, prop_y, cum_prop_y):
            b = list()
            for p, c in zip(prop_x, cum_prop_x):
                b.append([max(0., min(c, d) - max(c - p, d - q)) for q, d in zip(prop_y, cum_prop_y)])
            return np.matrix(b)

        s = np.asarray(self.start, float)
        m = self._m_pow(t)
        c = list()
        for prop_x, cum_prop_x, mean_x in zip(m.T, m.cumsum(1).T, self._underlying_mean(t)):
            r = list()
            for prop_y, cum_prop_y, mean_y in zip(m.T, m.cumsum(1).T, self._underlying_mean(t)):
                exy_m = _e_xy(list(prop_x.flat), list(cum_prop_x.flat), list(prop_y.flat), list(cum_prop_y.flat))
                exx = s.dot(exy_m).dot(s.T)[0, 0]
                cov_xy = exx - mean_x * mean_y
                cov_xy = max(0., cov_xy) if cov_xy > -EPS else cov_xy  # avoid numerical negatives
                r.append(cov_xy)
            c.append(r)
        return c


class FiniteStateContinuousTimeMarkovChain(FiniteStateMarkovChain):
    def __init__(self, transition=None, r_squared=1., start=None):
        super(FiniteStateContinuousTimeMarkovChain, self).__init__(transition, r_squared, start)
        self._transition_generator = logm(self._transition_matrix)

    def _m_pow(self, t, s=0.):
        return expm(self._transition_generator * (t - s))


class FiniteStateInhomogeneousMarkovChain(FiniteStateMarkovChain):
    @classmethod
    def random(cls, d=5, l=3):
        s = np.random.random((1, d))  # pick random vector or matrix with positive values
        s = s / s.sum(1)  # turn them into stochastic ones

        g = list()
        for _ in range(l):
            t = np.random.random((d, d))  # pick random vector or matrix with positive values
            t = t / t.sum(1).reshape((d, 1))  # turn them into stochastic ones
            g.append(t)

        # build process instance
        return cls(transition=g, start=list(s.flat))

    def __init__(self, transition=[None], r_squared=1., start=None):
        super(FiniteStateInhomogeneousMarkovChain, self).__init__(transition.pop(-1), r_squared, start)
        self._transition_grid = list(np.matrix(t, float) for t in transition)
        self._identity = np.identity(len(self.start), float)

    def _m_pow(self, t, s=0):
        l = len(self._transition_grid)
        # use transition grid at start
        n = self._identity
        for i in range(min(s, l), min(t, l)):
            n = n.dot(self._transition_grid[i])
        # use super beyond the transition grid
        return n * super(FiniteStateInhomogeneousMarkovChain, self)._m_pow(t, min(t, max(s, l)))


class FiniteStateAugmentedMarkovChain(FiniteStateMarkovChain):

    @property
    def func(self):
        return self._weights

    @classmethod
    def random(cls, d=5, weights=None):
        f = FiniteStateMarkovChain.random(d)
        return cls(f.transition, f.r_squared, weights, f.start)

    def __init__(self, transition=None, r_squared=1., weights=None, start=None):
        r"""

        :param list transition: stochastic matrix of transition probabilities,
                                i.e. np.ndarray with shape=2 and sum of each line equal to 1
                                (optional) default: identity matrix
        :param float r_squared: square of systematic correlation in factor simulation
                                (optional) default: 1.
        :param callable weights: function :math:`f:S \rightarrow \mathbb{R}`
                                 defined on single states to weight augmentation (aggregate) of state distributions
                                 (optional) default: :math:`f=id`
        :param list start: initial state distribution, i.e. np.ndarray with shape=1 or list, adding up to 1,
                           (optional) default: unique distribution

        """
        super(FiniteStateAugmentedMarkovChain, self).__init__(transition, r_squared, start)
        self._weights = (lambda x: 1.) if weights is None else weights
        self._underlying = FiniteStateMarkovChain(transition, r_squared, start)

    def eval(self, s):
        s = s.value if hasattr(s, 'value') else s
        return sum(x * self._weights(i) for i, x in enumerate(s))

    def mean(self, t):
        return self.eval(self._underlying_mean(t))

    def variance(self, t):
        w = np.array([self._weights(i) for i in range(len(self.start))], float)
        c = np.matrix(self._underlying_covariance(t), float)
        return w.dot(c).dot(w.T)[0, 0]
