"""Tiny dependency-free statistics helpers (weighted least squares, percentiles)."""
import math


def solve(a, b):
    """Solve a·x = b by Gaussian elimination with partial pivoting."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singular matrix")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                if f:
                    for c in range(col, n + 1):
                        m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def wls(X, y, w=None, ridge=1e-6):
    """Weighted (ridge-stabilised) least squares. Returns (coefs, r2, residuals)."""
    n, k = len(X), len(X[0])
    w = w or [1.0] * n
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for xi, yi, wi in zip(X, y, w):
        for a in range(k):
            xty[a] += wi * xi[a] * yi
            for b in range(a, k):
                xtx[a][b] += wi * xi[a] * xi[b]
    for a in range(k):
        for b in range(a):
            xtx[a][b] = xtx[b][a]
        if a > 0:  # don't penalise the intercept
            xtx[a][a] += ridge * sum(w)
    coefs = solve(xtx, xty)
    pred = [sum(c * v for c, v in zip(coefs, xi)) for xi in X]
    resid = [yi - pi for yi, pi in zip(y, pred)]
    wsum = sum(w)
    ybar = sum(wi * yi for wi, yi in zip(w, y)) / wsum
    ss_tot = sum(wi * (yi - ybar) ** 2 for wi, yi in zip(w, y))
    ss_res = sum(wi * r * r for wi, r in zip(w, resid))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return coefs, r2, resid


def percentile(values, q):
    """Linear-interpolated percentile, q in [0, 100]."""
    vals = sorted(values)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def weighted_median(values, weights):
    pairs = sorted((v, w) for v, w in zip(values, weights) if w > 0)
    if not pairs:
        return percentile(values, 50)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def clip(x, lo, hi):
    return max(lo, min(hi, x))
