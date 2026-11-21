"""Contour-diff & Bezier midpoint morphing utilities for SVG glyphs."""

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from fontTools.svgLib.path import SVGPath
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Identity


def cubic_pt(p0, p1, p2, p3, t: float):
    u = 1.0 - t
    return (
        u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
        u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1],
    )


def load_svg_dir(directory: Path) -> dict[int, tuple[Path, ET.Element]]:
    result = {}
    for p in sorted(directory.glob("*.svg")):
        root = ET.parse(p).getroot()
        cp_str = root.attrib.get("data-unicode", "")
        if cp_str.startswith("U+"):
            result[int(cp_str[2:], 16)] = (p, root)
    return result


def svg_to_contours(root: ET.Element, font_transform=Identity) -> list[list[tuple[float, float]]]:
    """Sample an SVG glyph's <path> into dense closed polyline contours in Y-up font coordinates."""
    path_elem = root.find("{http://www.w3.org/2000/svg}path")
    d = path_elem.attrib.get("d", "").strip() if path_elem is not None else ""
    if not d:
        return []
    baseline = int(root.attrib.get("data-baseline", "800"))
    unflip = Identity.translate(0, baseline).scale(1, -1)
    rp = RecordingPen()
    SVGPath.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>').draw(
        TransformPen(rp, font_transform.transform(unflip))
    )
    contours, cur, pos = [], [], None
    for op, pts in rp.value:
        if op == "moveTo":
            if cur:
                contours.append(cur)
            cur, pos = [pts[0]], pts[0]
        elif op == "lineTo":
            p1 = pts[0]
            for i in range(1, 9):
                t = i / 8.0
                cur.append((pos[0] + (p1[0] - pos[0]) * t, pos[1] + (p1[1] - pos[1]) * t))
            pos = p1
        elif op == "curveTo":
            p1, p2, p3 = pts
            for i in range(1, 17):
                cur.append(cubic_pt(pos, p1, p2, p3, i / 16.0))
            pos = p3
        elif op == "closePath":
            if cur and pos != cur[0]:
                p1 = cur[0]
                for i in range(1, 9):
                    t = i / 8.0
                    cur.append((pos[0] + (p1[0] - pos[0]) * t, pos[1] + (p1[1] - pos[1]) * t))
            if cur:
                contours.append(cur)
            cur = []
    if cur:
        contours.append(cur)
    return contours


def signed_area(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))


def resample_contour(pts: list[tuple[float, float]], n_samples: int = 120) -> list[tuple[float, float]]:
    dists = [0.0]
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        dists.append(dists[-1] + math.hypot(x2 - x1, y2 - y1))
    total = dists[-1]
    if total == 0:
        return [pts[0]] * n_samples
    out, j = [], 0
    for k in range(n_samples):
        target = (k / n_samples) * total
        while j < n - 1 and dists[j + 1] < target:
            j += 1
        seg = dists[j + 1] - dists[j]
        f = (target - dists[j]) / seg if seg > 0 else 0.0
        x1, y1 = pts[j]
        x2, y2 = pts[(j + 1) % n]
        out.append((x1 + (x2 - x1) * f, y1 + (y2 - y1) * f))
    return out


def best_cyclic_align(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    n = len(a)
    best_shift, best_err = 0, float("inf")
    for shift in range(n):
        err = sum(
            (a[i][0] - b[(i + shift) % n][0]) ** 2 + (a[i][1] - b[(i + shift) % n][1]) ** 2
            for i in range(0, n, 2)
        )
        if err < best_err:
            best_err, best_shift = err, shift
    return [b[(i + best_shift) % n] for i in range(n)]


def _turn_angle(p_prev, p_cur, p_next) -> float:
    """Exterior turning angle in [0, pi] at p_cur."""
    v1x, v1y = p_cur[0] - p_prev[0], p_cur[1] - p_prev[1]
    v2x, v2y = p_next[0] - p_cur[0], p_next[1] - p_cur[1]
    l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
    if l1 < 1e-6 or l2 < 1e-6:
        return 0.0
    cos_a = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (l1 * l2)))
    return math.acos(cos_a)


def detect_corners(pts: list[tuple[float, float]], angle_thresh: float = 0.50, k: int = 2) -> list[tuple[int, float]]:
    """Return sorted (index, turning_angle) for local-maximum sharp corners on a closed contour."""
    n = len(pts)
    if n < 2 * k + 1:
        return []
    angles = [_turn_angle(pts[(i - k) % n], pts[i], pts[(i + k) % n]) for i in range(n)]
    corners = []
    for i in range(n):
        if angles[i] >= angle_thresh:
            if all(angles[i] >= angles[(i + d) % n] for d in range(-k, k + 1) if d != 0):
                if not corners or (i - corners[-1][0]) > k:
                    corners.append((i, angles[i]))
    if len(corners) >= 2 and (corners[0][0] + n - corners[-1][0]) <= k:
        if corners[0][1] >= corners[-1][1]:
            corners.pop()
        else:
            corners.pop(0)
    return corners


def resample_open(pts: list[tuple[float, float]], n_samples: int) -> list[tuple[float, float]]:
    """Resample an open polyline from pts[0] to pts[-1] into n_samples points (inclusive)."""
    if n_samples <= 1 or len(pts) <= 1:
        return [pts[0]] * max(n_samples, 1)
    dists = [0.0]
    for i in range(len(pts) - 1):
        dists.append(dists[-1] + math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
    total = dists[-1]
    if total < 1e-9:
        return [pts[0]] * n_samples
    out, j = [pts[0]], 0
    for k in range(1, n_samples - 1):
        target = (k / (n_samples - 1)) * total
        while j + 1 < len(dists) - 1 and dists[j + 1] < target:
            j += 1
        seg_len = dists[j + 1] - dists[j]
        t = (target - dists[j]) / seg_len if seg_len > 0 else 0.0
        out.append((
            pts[j][0] + (pts[j + 1][0] - pts[j][0]) * t,
            pts[j][1] + (pts[j + 1][1] - pts[j][1]) * t,
        ))
    out.append(pts[-1])
    return out


def dp_match_corners(
    ra: list[tuple[float, float]],
    ca_idx: list[tuple[int, float]],
    rb: list[tuple[float, float]],
    cb_idx: list[tuple[int, float]],
    max_dist: float,
) -> list[tuple[int, int]]:
    """Monotonic Needleman-Wunsch alignment of sharp corners between two aligned contours."""
    m, n = len(ca_idx), len(cb_idx)
    if m == 0 or n == 0:
        return []
    skip_cost = max_dist * 0.65
    INF = 1e18
    dp = [[INF] * (n + 1) for _ in range(m + 1)]
    bt = [[0] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for i in range(1, m + 1):
        dp[i][0] = i * skip_cost
        bt[i][0] = 2
    for j in range(1, n + 1):
        dp[0][j] = j * skip_cost
        bt[0][j] = 3

    for i in range(1, m + 1):
        ia, ang_a = ca_idx[i - 1]
        pa = ra[ia]
        for j in range(1, n + 1):
            ib, ang_b = cb_idx[j - 1]
            pb = rb[ib]
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            best = dp[i - 1][j] + skip_cost
            move = 2
            if dp[i][j - 1] + skip_cost < best:
                best = dp[i][j - 1] + skip_cost
                move = 3
            if d <= max_dist:
                mc = dp[i - 1][j - 1] + d + abs(ang_a - ang_b) * (max_dist * 0.15)
                if mc < best:
                    best = mc
                    move = 1
            dp[i][j] = best
            bt[i][j] = move

    pairs = []
    i, j = m, n
    while i > 0 or j > 0:
        move = bt[i][j]
        if move == 1:
            pairs.append((ca_idx[i - 1][0], cb_idx[j - 1][0]))
            i -= 1
            j -= 1
        elif move == 2:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def morph_pair_smart(
    a: list[tuple[float, float]],
    b: list[tuple[float, float]],
    alpha: float,
    n_samples: int = 144,
) -> list[tuple[float, float]]:
    """Corner-anchored piecewise arc-length morph between two matched contours."""
    ra = resample_contour(a, n_samples)
    rb = resample_contour(b, n_samples)
    if (signed_area(ra) > 0) != (signed_area(rb) > 0):
        rb = list(reversed(rb))
    rb = best_cyclic_align(ra, rb)

    xs = [p[0] for p in ra]
    ys = [p[1] for p in ra]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    if diag < 1e-6:
        return ra

    corners_a = detect_corners(ra)
    corners_b = detect_corners(rb)
    matched = dp_match_corners(ra, corners_a, rb, corners_b, max_dist=diag * 0.30)

    if len(matched) < 2:
        return [
            ((1.0 - alpha) * p[0] + alpha * q[0], (1.0 - alpha) * p[1] + alpha * q[1])
            for p, q in zip(ra, rb)
        ]

    matched_a_set = {ia for ia, _ in matched}
    unmatched_a = [ia for ia, _ in corners_a if ia not in matched_a_set]

    out: list[tuple[float, float]] = []
    num_m = len(matched)
    for k in range(num_m):
        ia0, ib0 = matched[k]
        ia1, ib1 = matched[(k + 1) % num_m]

        span_a = ra[ia0:ia1 + 1] if ia1 > ia0 else ra[ia0:] + ra[:ia1 + 1]
        span_b = rb[ib0:ib1 + 1] if ib1 > ib0 else rb[ib0:] + rb[:ib1 + 1]
        span_idx_a = list(range(ia0, ia1 + 1)) if ia1 > ia0 else list(range(ia0, len(ra))) + list(range(0, ia1 + 1))

        steps = max(4, round((len(span_a) + len(span_b)) / 2))
        sa = resample_open(span_a, steps)
        sb = resample_open(span_b, steps)

        # Damp alpha smoothly near unmatched corners on base (e.g., Hack serifs absent in Route 138)
        has_unmatched = any(u in span_idx_a for u in unmatched_a)
        for idx_s, (p, q) in enumerate(zip(sa[:-1], sb[:-1])):
            local_alpha = alpha * 0.45 if has_unmatched else alpha
            out.append(((1.0 - local_alpha) * p[0] + local_alpha * q[0], (1.0 - local_alpha) * p[1] + local_alpha * q[1]))

    # Guard against self-crossing spans: if morphed area collapses, fall back to uniform arc-length
    min_src_area = min(abs(signed_area(ra)), abs(signed_area(rb)))
    if min_src_area > 0 and abs(signed_area(out)) < 0.65 * min_src_area:
        return [
            ((1.0 - alpha) * p[0] + alpha * q[0], (1.0 - alpha) * p[1] + alpha * q[1])
            for p, q in zip(ra, rb)
        ]
    return out


def _vertex_normals(pts: list[tuple[float, float]], is_ccw: bool) -> list[tuple[float, float]]:
    """Unit outward normals for each vertex of a closed contour."""
    n = len(pts)
    normals = []
    for i in range(n):
        p_prev = pts[(i - 1) % n]
        p_next = pts[(i + 1) % n]
        tx, ty = p_next[0] - p_prev[0], p_next[1] - p_prev[1]
        l = math.hypot(tx, ty)
        if l < 1e-9:
            normals.append((0.0, 0.0))
        elif is_ccw:
            # CCW outer contour: outward is right-hand normal (ty, -tx)
            normals.append((ty / l, -tx / l))
        else:
            # CW contour: outward is left-hand normal (-ty, tx)
            normals.append((-ty / l, tx / l))
    return normals


def _local_thickness(
    all_pts: list[tuple[float, float]],
    all_normals: list[tuple[float, float]],
    idx: int,
    max_w: float,
) -> float | None:
    """Estimate local stroke thickness at vertex `idx` by finding the nearest opposing edge along inward normal."""
    px, py = all_pts[idx]
    nx, ny = all_normals[idx]
    if nx == 0.0 and ny == 0.0:
        return None
    # Inward direction is -normal
    ix, iy = -nx, -ny
    best_d = max_w
    found = False
    for j, (qx, qy) in enumerate(all_pts):
        if j == idx:
            continue
        dx, dy = qx - px, qy - py
        # Quick bounding-box reject
        if abs(dx) > best_d or abs(dy) > best_d:
            continue
        proj = dx * ix + dy * iy
        if proj <= 2.0 or proj >= best_d:
            continue
        d = math.hypot(dx, dy)
        if d >= best_d:
            continue
        # Must lie within narrow cone (~25 deg) of inward normal and have opposing outward normal
        if (proj / d) > 0.90:
            qnx, qny = all_normals[j]
            if (qnx * nx + qny * ny) < -0.5:
                best_d = d
                found = True
    return best_d if found else None


def equalize_stroke_weight(
    morphed_contours: list[list[tuple[float, float]]],
    base_contours: list[list[tuple[float, float]]],
    strength: float = 0.65,
) -> list[list[tuple[float, float]]]:
    """Regularize local stroke thickness across a morphed glyph to match the base glyph's median stem weight."""
    if not morphed_contours or not base_contours:
        return morphed_contours

    # Compute base glyph median stroke weight as reference
    base_outer_ccw = signed_area(max(base_contours, key=lambda c: abs(signed_area(c)))) > 0
    b_pts, b_norms = [], []
    for c in base_contours:
        is_ccw = signed_area(c) > 0
        # For holes, flip normal so "inward" into ink is always -normal
        norms = _vertex_normals(c, is_ccw) if (is_ccw == base_outer_ccw) else [
            (-nx, -ny) for nx, ny in _vertex_normals(c, is_ccw)
        ]
        b_pts.extend(c)
        b_norms.extend(norms)

    xs = [p[0] for p in b_pts]
    ys = [p[1] for p in b_pts]
    max_w = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.35
    if max_w < 5.0:
        return morphed_contours

    # Sample every 3rd vertex on base for fast median stem thickness
    base_ws = [
        w for i in range(0, len(b_pts), 3)
        if (w := _local_thickness(b_pts, b_norms, i, max_w)) is not None
    ]
    if len(base_ws) < 6:
        return morphed_contours
    base_ws.sort()
    target_w = base_ws[len(base_ws) // 2]

    # Flatten morphed contours to measure cross-contour (outer <-> hole) thickness too
    m_outer_ccw = signed_area(max(morphed_contours, key=lambda c: abs(signed_area(c)))) > 0
    m_pts, m_norms, ranges = [], [], []
    for c in morphed_contours:
        start = len(m_pts)
        is_ccw = signed_area(c) > 0
        norms = _vertex_normals(c, is_ccw) if (is_ccw == m_outer_ccw) else [
            (-nx, -ny) for nx, ny in _vertex_normals(c, is_ccw)
        ]
        m_pts.extend(c)
        m_norms.extend(norms)
        ranges.append((start, len(m_pts)))

    # Compute smooth per-vertex outward normal shift to bring pinched/bulged strokes toward target_w
    raw_shifts: list[float | None] = [None] * len(m_pts)
    for i in range(len(m_pts)):
        w = _local_thickness(m_pts, m_norms, i, max_w)
        if w is not None and 0.45 * target_w <= w <= 1.65 * target_w:
            delta = 0.5 * (target_w - w) * strength
            raw_shifts[i] = max(-0.20 * target_w, min(0.20 * target_w, delta))

    # Fill None gaps (corners/tips) by interpolating from nearest measured neighbors, then smooth
    result = []
    for start, end in ranges:
        n = end - start
        c_raw = raw_shifts[start:end]
        valid = [i for i, v in enumerate(c_raw) if v is not None]
        if not valid:
            c_shifts = [0.0] * n
        else:
            c_shifts = [0.0] * n
            for i in range(n):
                if c_raw[i] is not None:
                    c_shifts[i] = c_raw[i]
                else:
                    # Find nearest valid predecessor and successor circularly
                    prev_i = max((v for v in valid if v < i), default=valid[-1])
                    next_i = min((v for v in valid if v > i), default=valid[0])
                    d_prev = (i - prev_i) % n
                    d_next = (next_i - i) % n
                    t = d_prev / (d_prev + d_next) if (d_prev + d_next) > 0 else 0.5
                    c_shifts[i] = (1.0 - t) * c_raw[prev_i] + t * c_raw[next_i]

        smooth = [
            (
                c_shifts[(i - 2) % n]
                + 2.0 * c_shifts[(i - 1) % n]
                + 3.0 * c_shifts[i]
                + 2.0 * c_shifts[(i + 1) % n]
                + c_shifts[(i + 2) % n]
            ) / 9.0
            for i in range(n)
        ]
        new_c = []
        for i in range(n):
            px, py = m_pts[start + i]
            nx, ny = m_norms[start + i]
            s = smooth[i]
            new_c.append((px + nx * s, py + ny * s))
        result.append(new_c)
    return result


def taubin_fair_contour(pts: list[tuple[float, float]], iters: int = 3) -> list[tuple[float, float]]:
    """Volume-preserving Taubin smoothing on non-corner interior points to remove micro-wobbles."""
    n = len(pts)
    if n < 8:
        return pts
    corner_set = {idx for idx, _ in detect_corners(pts, angle_thresh=0.45, k=2)}
    # Pin each sharp corner and its immediate neighbor so corners stay razor-sharp
    pinned = set()
    for c in corner_set:
        pinned.add(c)
        pinned.add((c - 1) % n)
        pinned.add((c + 1) % n)

    cur = list(pts)
    for _ in range(iters):
        for factor in (0.45, -0.47):
            nxt = list(cur)
            for i in range(n):
                if i in pinned:
                    continue
                p_prev = cur[(i - 1) % n]
                p_next = cur[(i + 1) % n]
                mx = 0.5 * (p_prev[0] + p_next[0])
                my = 0.5 * (p_prev[1] + p_next[1])
                nxt[i] = (cur[i][0] + factor * (mx - cur[i][0]), cur[i][1] + factor * (my - cur[i][1]))
            cur = nxt
    return cur


def snap_hv_span(span: list[tuple[float, float]], tol: float, max_angle_deg: float = 3.5) -> list[tuple[float, float]]:
    """Snap near-horizontal or near-vertical straight spans to exact H/V lines."""
    if len(span) < 2 or _max_line_err(span) > tol * 1.2:
        return span
    p0, p1 = span[0], span[-1]
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-6:
        return span
    ang_h = math.degrees(math.atan2(abs(dy), abs(dx)))
    ang_v = math.degrees(math.atan2(abs(dx), abs(dy)))
    if ang_h <= max_angle_deg:
        ym = 0.5 * (p0[1] + p1[1])
        return [(p0[0], ym), (p1[0], ym)]
    if ang_v <= max_angle_deg:
        xm = 0.5 * (p0[0] + p1[0])
        return [(xm, p0[1]), (xm, p1[1])]
    return span


def morph_contours(
    root_a: ET.Element,
    root_b: ET.Element,
    transform_b=Identity,
    alpha: float = 0.5,
    n_samples: int = 144,
) -> list[list[tuple[float, float]]] | None:
    """Overlay root_b onto root_a and compute corner-anchored, stroke-equalized, faired midpoint contours."""
    ca = svg_to_contours(root_a)
    cb = svg_to_contours(root_b, transform_b)
    if not ca or not cb or len(ca) != len(cb):
        return None

    all_a = [p for c in ca for p in c]
    all_b = [p for c in cb for p in c]
    ax = (min(p[0] for p in all_a) + max(p[0] for p in all_a)) * 0.5
    bx = (min(p[0] for p in all_b) + max(p[0] for p in all_b)) * 0.5
    dx = ax - bx
    cb = [[(p[0] + dx, p[1]) for p in c] for c in cb]

    def centroid(c):
        return (sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c))

    outer_sign_a = signed_area(max(ca, key=lambda c: abs(signed_area(c)))) > 0
    outer_sign_b = signed_area(max(cb, key=lambda c: abs(signed_area(c)))) > 0

    used_b: set[int] = set()
    pairs = []
    for a in ca:
        is_outer_a = (signed_area(a) > 0) == outer_sign_a
        cx_a, cy_a = centroid(a)
        best_j, best_cost = None, float("inf")
        for j, b in enumerate(cb):
            if j in used_b:
                continue
            is_outer_b = (signed_area(b) > 0) == outer_sign_b
            cx_b, cy_b = centroid(b)
            cost = (cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2 + (0 if is_outer_a == is_outer_b else 1e12)
            if cost < best_cost:
                best_cost, best_j = cost, j
        used_b.add(best_j)
        pairs.append((a, cb[best_j]))

    morphed = [morph_pair_smart(a, b, alpha, n_samples) for a, b in pairs]
    equalized = equalize_stroke_weight(morphed, [resample_contour(a, n_samples) for a, _ in pairs], strength=0.45)
    return [taubin_fair_contour(c, iters=3) for c in equalized]


# --- Schneider's Cubic Bezier Curve Fitter ---

def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _vadd(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _vmul(a, s):
    return (a[0] * s, a[1] * s)


def _vdot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _vnorm(a):
    l = math.hypot(a[0], a[1])
    return (a[0] / l, a[1] / l) if l > 1e-9 else (0.0, 0.0)


def _max_line_err(pts: list[tuple[float, float]]) -> float:
    p0, p1 = pts[0], pts[-1]
    vx, vy = p1[0] - p0[0], p1[1] - p0[1]
    seg_len = math.hypot(vx, vy)
    if seg_len < 1e-9:
        return max(math.hypot(p[0] - p0[0], p[1] - p0[1]) for p in pts)
    return max(abs((p[0] - p0[0]) * vy - (p[1] - p0[1]) * vx) / seg_len for p in pts)


def _fit_cubic_span(
    pts: list[tuple[float, float]],
    t_hat1: tuple[float, float],
    t_hat2: tuple[float, float],
    tol: float,
    depth: int = 0,
) -> list[tuple]:
    """Fit clean L or cubic C segments to an open point span using Schneider's algorithm."""
    if len(pts) <= 2 or _max_line_err(pts) <= tol * 0.75:
        return [("L", pts[-1])]

    u = [0.0]
    for i in range(1, len(pts)):
        u.append(u[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = u[-1]
    if total < 1e-9:
        return [("L", pts[-1])]
    u = [x / total for x in u]

    p0, p3 = pts[0], pts[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for pt, t in zip(pts, u):
        mt = 1.0 - t
        b0 = mt * mt * mt
        b1 = 3.0 * mt * mt * t
        b2 = 3.0 * mt * t * t
        b3 = t * t * t
        a1 = _vmul(t_hat1, b1)
        a2 = _vmul(t_hat2, b2)
        c00 += _vdot(a1, a1)
        c01 += _vdot(a1, a2)
        c11 += _vdot(a2, a2)
        tmp = _vsub(pt, _vadd(_vmul(p0, b0 + b1), _vmul(p3, b2 + b3)))
        x0 += _vdot(a1, tmp)
        x1 += _vdot(a2, tmp)

    det = c00 * c11 - c01 * c01
    alpha1 = (c11 * x0 - c01 * x1) / det if abs(det) > 1e-9 else 0.0
    alpha2 = (c00 * x1 - c01 * x0) / det if abs(det) > 1e-9 else 0.0

    seg_len = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    eps = 1e-6 * seg_len
    if alpha1 < eps or alpha2 < eps or alpha1 > seg_len * 2.0 or alpha2 > seg_len * 2.0:
        alpha1 = alpha2 = seg_len / 3.0

    p1 = _vadd(p0, _vmul(t_hat1, alpha1))
    p2 = _vadd(p3, _vmul(t_hat2, alpha2))

    max_err, split = 0.0, len(pts) // 2
    for i, (pt, t) in enumerate(zip(pts, u)):
        q = cubic_pt(p0, p1, p2, p3, t)
        err = math.hypot(pt[0] - q[0], pt[1] - q[1])
        if err > max_err:
            max_err, split = err, i

    if max_err <= tol or depth >= 5 or len(pts) <= 4:
        return [("C", p1, p2, p3)]

    split = max(2, min(len(pts) - 3, split))
    t_mid = _vnorm(_vsub(pts[split + 1], pts[split - 1]))
    left = _fit_cubic_span(pts[:split + 1], t_hat1, (-t_mid[0], -t_mid[1]), tol, depth + 1)
    right = _fit_cubic_span(pts[split:], t_mid, t_hat2, tol, depth + 1)
    return left + right


def contours_to_svg_path(contours: list[list[tuple[float, float]]], baseline: int) -> str:
    """Convert Y-up font contours to a clean Y-down SVG path using snapped L and fitted cubic C curves."""
    tol = 1.5 if baseline <= 1000 else 3.0
    parts = []
    for c in contours:
        if len(c) < 3:
            continue
        corners = [idx for idx, _ in detect_corners(c, angle_thresh=0.45, k=2)]
        if len(corners) == 0:
            i_min = min(range(len(c)), key=lambda i: c[i][1])
            i_max = max(range(len(c)), key=lambda i: c[i][1])
            corners = sorted({i_min, i_max})
        elif len(corners) == 1:
            opp = (corners[0] + len(c) // 2) % len(c)
            corners = sorted({corners[0], opp})

        start = c[corners[0]]
        seg = [f"M{round(start[0], 1)},{round(baseline - start[1], 1)}"]
        num_c = len(corners)
        for k in range(num_c):
            i0 = corners[k]
            i1 = corners[(k + 1) % num_c]
            span = c[i0:i1 + 1] if i1 > i0 else c[i0:] + c[:i1 + 1]
            if len(span) < 2:
                continue
            span = snap_hv_span(span, tol)
            t1 = _vnorm(_vsub(span[min(2, len(span) - 1)], span[0]))
            t2 = _vnorm(_vsub(span[max(0, len(span) - 3)], span[-1]))
            for cmd in _fit_cubic_span(span, t1, t2, tol):
                if cmd[0] == "L":
                    p = cmd[1]
                    seg.append(f"L{round(p[0], 1)},{round(baseline - p[1], 1)}")
                else:
                    _, p1, p2, p3 = cmd
                    seg.append(
                        f"C{round(p1[0], 1)},{round(baseline - p1[1], 1)} "
                        f"{round(p2[0], 1)},{round(baseline - p2[1], 1)} "
                        f"{round(p3[0], 1)},{round(baseline - p3[1], 1)}"
                    )
        seg.append("Z")
        parts.append("".join(seg))
    return " ".join(parts)
