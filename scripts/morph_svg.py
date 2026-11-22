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


def detect_corners(pts: list[tuple[float, float]], angle_thresh: float = 0.50, k: int = 1) -> list[tuple[int, float]]:
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

        # Keep straight spans rigid (uniform offset) so stroke intersections never flare or pinch
        c_pts = m_pts[start:end]
        c_norms = m_norms[start:end]
        new_c = [
            (c_pts[i][0] + c_norms[i][0] * smooth[i], c_pts[i][1] + c_norms[i][1] * smooth[i])
            for i in range(n)
        ]

        corners = [idx for idx, _ in detect_corners(c_pts, angle_thresh=0.45, k=1)]
        if len(corners) >= 2:
            line_tol = max(2.0, target_w * 0.04)
            num_c = len(corners)
            # For each straight span, record its shifted line (point, unit_dir)
            span_lines: list[tuple[tuple[float, float], tuple[float, float]] | None] = [None] * num_c
            span_indices: list[list[int]] = []
            for k in range(num_c):
                i0 = corners[k]
                i1 = corners[(k + 1) % num_c]
                idxs = list(range(i0, i1 + 1)) if i1 > i0 else list(range(i0, n)) + list(range(0, i1 + 1))
                span_indices.append(idxs)
                span_pts = [c_pts[i] for i in idxs]
                if len(span_pts) >= 3 and _max_line_err(span_pts) <= line_tol:
                    p0, p1 = span_pts[0], span_pts[-1]
                    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                    seg_len = math.hypot(dx, dy)
                    if seg_len > 1e-6:
                        ux, uy = dx / seg_len, dy / seg_len
                        # Use interior median shift so junction rays at endpoints don't bias the span
                        interior = idxs[1:-1]
                        mid_shifts = sorted(c_shifts[i] for i in interior)
                        u_shift = mid_shifts[len(mid_shifts) // 2]
                        # Align constant span normal with the contour's outward normal
                        mx, my = c_norms[interior[len(interior) // 2]]
                        nx, ny = (uy, -ux) if (uy * mx - ux * my) >= 0 else (-uy, ux)
                        q0 = (p0[0] + nx * u_shift, p0[1] + ny * u_shift)
                        span_lines[k] = (q0, (ux, uy))
                        for i in interior:
                            new_c[i] = (c_pts[i][0] + nx * u_shift, c_pts[i][1] + ny * u_shift)

            # Recompute corners where two straight spans meet as their exact line intersection
            for k in range(num_c):
                l_prev = span_lines[(k - 1) % num_c]
                l_next = span_lines[k]
                ci = corners[k]
                if l_prev is not None and l_next is not None:
                    (x1, y1), (ux1, uy1) = l_prev
                    (x2, y2), (ux2, uy2) = l_next
                    denom = ux1 * uy2 - uy1 * ux2
                    if abs(denom) > 0.15:
                        t = ((x2 - x1) * uy2 - (y2 - y1) * ux2) / denom
                        ix, iy = x1 + t * ux1, y1 + t * uy1
                        if math.hypot(ix - c_pts[ci][0], iy - c_pts[ci][1]) <= 0.35 * target_w:
                            new_c[ci] = (ix, iy)
                elif l_prev is not None:
                    (x1, y1), (ux1, uy1) = l_prev
                    t = (c_pts[ci][0] - x1) * ux1 + (c_pts[ci][1] - y1) * uy1
                    new_c[ci] = (x1 + t * ux1, y1 + t * uy1)
                elif l_next is not None:
                    (x2, y2), (ux2, uy2) = l_next
                    t = (c_pts[ci][0] - x2) * ux2 + (c_pts[ci][1] - y2) * uy2
                    new_c[ci] = (x2 + t * ux2, y2 + t * uy2)

        result.append(new_c)
    return result


def taubin_fair_contour(pts: list[tuple[float, float]], iters: int = 3) -> list[tuple[float, float]]:
    """Volume-preserving Taubin smoothing on non-corner interior points to remove micro-wobbles."""
    n = len(pts)
    if n < 8:
        return pts
    corner_set = {idx for idx, _ in detect_corners(pts, angle_thresh=0.45, k=1)}
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


def _max_chamfer_distance(
    ca: list[list[tuple[float, float]]],
    cb: list[list[tuple[float, float]]],
    n_pts: int = 64,
) -> float:
    """Max unit-box normalized Chamfer distance across paired outer/inner contours."""
    def norm(c):
        pts = resample_contour(c, n_pts)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = max(max(xs) - min(xs), 1e-6)
        h = max(max(ys) - min(ys), 1e-6)
        x0, y0 = min(xs), min(ys)
        return [((p[0] - x0) / w, (p[1] - y0) / h) for p in pts]

    # Compare largest (outer) contour + check relative counter centroid shift
    oa_raw = max(ca, key=lambda c: abs(signed_area(c)))
    ob_raw = max(cb, key=lambda c: abs(signed_area(c)))
    oa, ob = norm(oa_raw), norm(ob_raw)
    dists_a = [min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in ob) for p in oa]
    dists_b = [min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in oa) for p in ob]
    max_d = 0.5 * (sum(dists_a) + sum(dists_b)) / n_pts
    # Catch local structural mismatches (e.g. G with vs without crossbar) via Hausdorff distance
    hd = max(max(dists_a), max(dists_b))
    if hd > 0.22:
        max_d = max(max_d, hd * 0.5)

    # Also check if inner counters sit at incompatible positions inside the outer bounding box
    if len(ca) > 1 and len(ca) == len(cb):
        ax0, ax1 = min(p[0] for p in oa_raw), max(p[0] for p in oa_raw)
        ay0, ay1 = min(p[1] for p in oa_raw), max(p[1] for p in oa_raw)
        bx0, bx1 = min(p[0] for p in ob_raw), max(p[0] for p in ob_raw)
        by0, by1 = min(p[1] for p in ob_raw), max(p[1] for p in ob_raw)
        aw, ah = max(ax1 - ax0, 1e-6), max(ay1 - ay0, 1e-6)
        bw, bh = max(bx1 - bx0, 1e-6), max(by1 - by0, 1e-6)
        holes_a = [c for c in ca if c is not oa_raw]
        holes_b = [c for c in cb if c is not ob_raw]
        for ha in holes_a:
            cxa = (sum(p[0] for p in ha) / len(ha) - ax0) / aw
            cya = (sum(p[1] for p in ha) / len(ha) - ay0) / ah
            best = min(
                math.hypot(
                    cxa - (sum(p[0] for p in hb) / len(hb) - bx0) / bw,
                    cya - (sum(p[1] for p in hb) / len(hb) - by0) / bh,
                )
                for hb in holes_b
            )
            if best > 0.14:
                max_d = max(max_d, best)
    return max_d


def _measure_hv_weights(contours: list[list[tuple[float, float]]]) -> tuple[float | None, float | None]:
    """Measure median vertical-stem weight (|nx| > 0.7) and horizontal-bar weight (|ny| > 0.7)."""
    if not contours:
        return None, None
    outer_ccw = signed_area(max(contours, key=lambda c: abs(signed_area(c)))) > 0
    pts, norms = [], []
    for c in contours:
        is_ccw = signed_area(c) > 0
        ns = _vertex_normals(c, is_ccw) if (is_ccw == outer_ccw) else [(-nx, -ny) for nx, ny in _vertex_normals(c, is_ccw)]
        pts.extend(c)
        norms.extend(ns)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    max_w = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.35
    if max_w < 5.0:
        return None, None
    ws_v, ws_h = [], []
    for i in range(0, len(pts), 2):
        w = _local_thickness(pts, norms, i, max_w)
        if w is None:
            continue
        nx, ny = norms[i]
        if abs(nx) > 0.7:
            ws_v.append(w)
        elif abs(ny) > 0.7:
            ws_h.append(w)
    ws_v.sort()
    ws_h.sort()
    wv = ws_v[len(ws_v) // 2] if ws_v else None
    wh = ws_h[len(ws_h) // 2] if ws_h else None
    if wv is None:
        wv = wh
    if wh is None:
        wh = wv
    return wv, wh


def style_transfer_contours(
    ca: list[list[tuple[float, float]]],
    cb: list[list[tuple[float, float]]],
    alpha: float = 0.45,
    n_samples: int = 144,
) -> list[list[tuple[float, float]]]:
    """Topology-preserving style transfer for mismatched glyphs:
    1. Gentle 2D proportion warp (FFD) toward cb's vertical/horizontal landmarks
    2. Anisotropic H/V stroke-contrast transfer toward cb's stem/bar weights
    3. Curve-tension transfer (subtle superellipse squaring on curved spans)
    """
    ra_list = [resample_contour(c, n_samples) for c in ca]
    rb_list = [resample_contour(c, n_samples) for c in cb]

    # 1. Gentle 2D proportion warp (preserving baseline near 0 and monospace centering)
    all_a = [p for c in ra_list for p in c]
    all_b = [p for c in rb_list for p in c]
    ax0, ax1 = min(p[0] for p in all_a), max(p[0] for p in all_a)
    ay0, ay1 = min(p[1] for p in all_a), max(p[1] for p in all_a)
    bx0, bx1 = min(p[0] for p in all_b), max(p[0] for p in all_b)
    by0, by1 = min(p[1] for p in all_b), max(p[1] for p in all_b)
    aw, ah = max(ax1 - ax0, 1e-6), max(ay1 - ay0, 1e-6)
    bw, bh = max(bx1 - bx0, 1e-6), max(by1 - by0, 1e-6)
    acx = 0.5 * (ax0 + ax1)
    ay_mid = sum(p[1] for p in all_a) / len(all_a)
    by_mid = sum(p[1] for p in all_b) / len(all_b)

    sx = 1.0 + max(-0.15, min(0.15, (bw / aw - 1.0) * alpha * 0.35))
    ty0 = ay0 if abs(ay0) < 25.0 else ay0 + (by0 - ay0) * alpha * 0.4
    ty1 = ay1 + (by1 - ay1) * alpha * 0.4
    t_mid_shift = max(-0.08 * ah, min(0.08 * ah, (by_mid - ay_mid) * alpha * 0.4))

    warped = []
    for c in ra_list:
        wc = []
        for x, y in c:
            nx = acx + (x - acx) * sx
            u = (y - ay0) / ah
            # Smooth bell bump for vertical midpoint landmark
            ny = ty0 + u * (ty1 - ty0) + 4.0 * u * (1.0 - u) * t_mid_shift
            wc.append((nx, ny))
        warped.append(wc)

    # 2. Anisotropic H/V contrast transfer
    awv, awh = _measure_hv_weights(warped)
    bwv, bwh = _measure_hv_weights(rb_list)
    if awv and bwv and awh and bwh:
        target_v = (1.0 - alpha) * awv + alpha * bwv
        target_h = (1.0 - alpha) * awh + alpha * bwh
        outer_ccw = signed_area(max(warped, key=lambda c: abs(signed_area(c)))) > 0
        m_pts, m_norms, ranges = [], [], []
        for c in warped:
            start = len(m_pts)
            is_ccw = signed_area(c) > 0
            ns = _vertex_normals(c, is_ccw) if (is_ccw == outer_ccw) else [(-nx, -ny) for nx, ny in _vertex_normals(c, is_ccw)]
            m_pts.extend(c)
            m_norms.extend(ns)
            ranges.append((start, len(m_pts)))

        max_w = max(aw, ah) * 0.35
        raw_shifts: list[float | None] = [None] * len(m_pts)
        for i in range(len(m_pts)):
            w = _local_thickness(m_pts, m_norms, i, max_w)
            if w is None:
                continue
            nx, ny = m_norms[i]
            t_w = target_v * (nx * nx) + target_h * (ny * ny)
            if 0.45 * t_w <= w <= 1.65 * t_w:
                delta = 0.5 * (t_w - w) * 0.65
                raw_shifts[i] = max(-0.22 * t_w, min(0.22 * t_w, delta))

        styled = []
        for start, end in ranges:
            n = end - start
            c_pts = m_pts[start:end]
            c_norms = m_norms[start:end]
            c_raw = raw_shifts[start:end]
            valid = [i for i, v in enumerate(c_raw) if v is not None]
            c_shifts = [0.0] * n
            if valid:
                for i in range(n):
                    if c_raw[i] is not None:
                        c_shifts[i] = c_raw[i]
                    else:
                        prev_i = max((v for v in valid if v < i), default=valid[-1])
                        next_i = min((v for v in valid if v > i), default=valid[0])
                        d_prev, d_next = (i - prev_i) % n, (next_i - i) % n
                        t = d_prev / (d_prev + d_next) if (d_prev + d_next) > 0 else 0.5
                        c_shifts[i] = (1.0 - t) * c_raw[prev_i] + t * c_raw[next_i]

            smooth = [
                (c_shifts[(i - 2) % n] + 2.0 * c_shifts[(i - 1) % n] + 3.0 * c_shifts[i]
                 + 2.0 * c_shifts[(i + 1) % n] + c_shifts[(i + 2) % n]) / 9.0
                for i in range(n)
            ]
            # 3. Curve-tension transfer: subtle superellipse push on curved non-corner diagonals
            corner_set = {idx for idx, _ in detect_corners(c_pts, angle_thresh=0.45, k=1)}
            tension_amp = 0.012 * min(aw, ah) * alpha
            new_c = []
            for i in range(n):
                px, py = c_pts[i]
                nx, ny = c_norms[i]
                s = smooth[i]
                if i not in corner_set:
                    # 45° diagonals (|nx*ny| = 0.5) get gentle outward superellipse tension
                    s += tension_amp * (2.0 * abs(nx * ny))
                new_c.append((px + nx * s, py + ny * s))
            styled.append(new_c)
        warped = styled

    return [taubin_fair_contour(c, iters=2) for c in warped]


# --- Native Bezier-Segment Morphing Engine ---

def _lerp_pt(a, b, t: float):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _split_cubic(seg, t: float):
    """Exact de Casteljau subdivision of cubic segment (p0, p1, p2, p3) at parameter t in (0, 1)."""
    p0, p1, p2, p3 = seg
    q0 = _lerp_pt(p0, p1, t)
    q1 = _lerp_pt(p1, p2, t)
    q2 = _lerp_pt(p2, p3, t)
    r0 = _lerp_pt(q0, q1, t)
    r1 = _lerp_pt(q1, q2, t)
    s0 = _lerp_pt(r0, r1, t)
    return (p0, q0, r0, s0), (s0, r1, q2, p3)


def _seg_len(seg) -> float:
    p0, p1, p2, p3 = seg
    # 4-chord arc-length approximation
    pts = [p0, cubic_pt(p0, p1, p2, p3, 0.25), cubic_pt(p0, p1, p2, p3, 0.5), cubic_pt(p0, p1, p2, p3, 0.75), p3]
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(4))


def _seg_is_line(seg, tol: float = 0.5) -> bool:
    p0, p1, p2, p3 = seg
    vx, vy = p3[0] - p0[0], p3[1] - p0[1]
    l = math.hypot(vx, vy)
    if l < 1e-6:
        return True
    d1 = abs((p1[0] - p0[0]) * vy - (p1[1] - p0[1]) * vx) / l
    d2 = abs((p2[0] - p0[0]) * vy - (p2[1] - p0[1]) * vx) / l
    return d1 <= tol and d2 <= tol


def _reverse_bezier_contour(segs):
    return [(p3, p2, p1, p0) for p0, p1, p2, p3 in reversed(segs)]


def _bezier_signed_area(segs) -> float:
    pts = []
    for p0, p1, p2, p3 in segs:
        pts.append(p0)
        pts.append(cubic_pt(p0, p1, p2, p3, 0.5))
    return signed_area(pts)


def svg_to_bezier_contours(root: ET.Element, font_transform=Identity) -> list[list[tuple]]:
    """Extract native closed cubic Bezier segment contours [(p0, p1, p2, p3), ...] in Y-up font coords."""
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

    def make_line(a, b):
        return (a, _lerp_pt(a, b, 1.0 / 3.0), _lerp_pt(a, b, 2.0 / 3.0), b)

    contours, cur, start, pos = [], [], None, None
    for op, pts in rp.value:
        if op == "moveTo":
            if cur:
                contours.append(cur)
            cur, start, pos = [], pts[0], pts[0]
        elif op == "lineTo":
            p3 = pts[0]
            if math.hypot(p3[0] - pos[0], p3[1] - pos[1]) > 1e-4:
                cur.append(make_line(pos, p3))
                pos = p3
        elif op == "curveTo":
            p1, p2, p3 = pts
            if math.hypot(p3[0] - pos[0], p3[1] - pos[1]) > 1e-4 or math.hypot(p1[0] - pos[0], p1[1] - pos[1]) > 1e-4:
                cur.append((pos, p1, p2, p3))
                pos = p3
        elif op == "qCurveTo":
            # Degree-elevate TrueType quadratic splines to exact cubics
            qpts = list(pts)
            if qpts[-1] is None:
                continue
            for idx in range(len(qpts) - 1):
                q = qpts[idx]
                p3 = qpts[idx + 1] if idx == len(qpts) - 2 else _lerp_pt(q, qpts[idx + 1], 0.5)
                c1 = _lerp_pt(pos, q, 2.0 / 3.0)
                c2 = _lerp_pt(p3, q, 2.0 / 3.0)
                if math.hypot(p3[0] - pos[0], p3[1] - pos[1]) > 1e-4:
                    cur.append((pos, c1, c2, p3))
                    pos = p3
        elif op == "closePath":
            if start is not None and pos is not None and math.hypot(start[0] - pos[0], start[1] - pos[1]) > 1e-4:
                cur.append(make_line(pos, start))
            if cur:
                contours.append(cur)
            cur, start, pos = [], None, None
    if cur:
        contours.append(cur)
    return [c for c in contours if len(c) >= 2]


def _bezier_corners(segs: list[tuple], angle_thresh: float = 0.45) -> list[tuple[int, float]]:
    """Detect sharp on-curve corners where incoming and outgoing segment tangents turn > angle_thresh."""
    n = len(segs)
    corners = []
    for i in range(n):
        prev_s = segs[(i - 1) % n]
        next_s = segs[i]
        # Incoming tangent at prev_s end
        v_in = _vsub(prev_s[3], prev_s[2])
        if math.hypot(*v_in) < 1e-4:
            v_in = _vsub(prev_s[3], prev_s[0])
        # Outgoing tangent at next_s start
        v_out = _vsub(next_s[1], next_s[0])
        if math.hypot(*v_out) < 1e-4:
            v_out = _vsub(next_s[3], next_s[0])
        li, lo = math.hypot(*v_in), math.hypot(*v_out)
        if li > 1e-6 and lo > 1e-6:
            cos_a = max(-1.0, min(1.0, (v_in[0] * v_out[0] + v_in[1] * v_out[1]) / (li * lo)))
            ang = math.acos(cos_a)
            if ang >= angle_thresh:
                corners.append((i, ang))
    return corners


def _slice_cubic(seg, t0: float, t1: float):
    """Exact de Casteljau sub-curve of cubic seg over [t0, t1] subset [0, 1]."""
    if t0 <= 1e-6 and t1 >= 1.0 - 1e-6:
        return seg
    cur = seg
    if t0 > 1e-6:
        _, cur = _split_cubic(cur, t0)
        t1 = (t1 - t0) / (1.0 - t0)
    if t1 < 1.0 - 1e-6:
        cur, _ = _split_cubic(cur, t1)
    return cur


def _resample_span_at_breaks(span: list[tuple], breaks: list[float]) -> list[tuple]:
    """Slice a native cubic span at exact normalized arc-length intervals [breaks[k], breaks[k+1]]."""
    lens = [_seg_len(s) for s in span]
    total = max(sum(lens), 1e-6)
    cum = [0.0]
    for l in lens:
        cum.append(cum[-1] + l / total)
    cum[-1] = 1.0

    def seg_at(u: float) -> tuple[int, float]:
        for idx in range(len(span)):
            if u <= cum[idx + 1] + 1e-9 or idx == len(span) - 1:
                du = max(cum[idx + 1] - cum[idx], 1e-9)
                return idx, max(0.0, min(1.0, (u - cum[idx]) / du))
        return len(span) - 1, 1.0

    out = []
    for k in range(len(breaks) - 1):
        u0, u1 = breaks[k], breaks[k + 1]
        if u1 - u0 < 1e-6:
            continue
        i0, t0 = seg_at(u0)
        i1, t1 = seg_at(u1)
        if i0 == i1:
            out.append(_slice_cubic(span[i0], t0, t1))
        else:
            # Interval crosses an original breakpoint; take the dominant sub-segment
            # (breaks already includes all original breakpoints, so this only happens if snapped within 0.02)
            out.append(_slice_cubic(span[i0], t0, 1.0) if (cum[i0 + 1] - u0) >= (u1 - cum[i1]) else _slice_cubic(span[i1], 0.0, t1))
    return out


def _morph_bezier_span(span_a: list[tuple], span_b: list[tuple], alpha: float) -> list[tuple]:
    """Slice two native cubic spans at their exact union of normalized arc-length breakpoints and interpolate."""
    def norm_breaks(sp):
        ls = [_seg_len(s) for s in sp]
        tot = sum(ls)
        if tot < 1e-6:
            return []
        c, acc = [], 0.0
        for l in ls[:-1]:
            acc += l / tot
            c.append(acc)
        return c

    merged = sorted([0.0] + norm_breaks(span_a) + norm_breaks(span_b) + [1.0])
    breaks = [0.0]
    for u in merged[1:-1]:
        if u - breaks[-1] > 0.015 and 1.0 - u > 0.015:
            breaks.append(u)
    breaks.append(1.0)

    sub_a = _resample_span_at_breaks(span_a, breaks)
    sub_b = _resample_span_at_breaks(span_b, breaks)

    out = []
    for sa, sb in zip(sub_a, sub_b):
        out.append(tuple(_lerp_pt(sa[k], sb[k], alpha) for k in range(4)))
    return out


def morph_bezier_contour(segs_a: list[tuple], segs_b: list[tuple], alpha: float) -> list[tuple]:
    """Native Bezier-segment contour morphing with corner-anchored DP alignment and de Casteljau subdivision."""
    if (_bezier_signed_area(segs_a) > 0) != (_bezier_signed_area(segs_b) > 0):
        segs_b = _reverse_bezier_contour(segs_b)

    # Rotate segs_b so start vertex is closest to segs_a[0][0]
    p0_a = segs_a[0][0]
    best_rot = min(range(len(segs_b)), key=lambda i: math.hypot(segs_b[i][0][0] - p0_a[0], segs_b[i][0][1] - p0_a[1]))
    segs_b = segs_b[best_rot:] + segs_b[:best_rot]

    ca = _bezier_corners(segs_a)
    cb = _bezier_corners(segs_b)

    if len(ca) >= 2 and len(cb) >= 2:
        # Align corners by circular Needleman-Wunsch DP on normalized arc-length position + angle
        def seg_cum_u(segs):
            ls = [_seg_len(s) for s in segs]
            tot = max(sum(ls), 1e-6)
            u, acc = [0.0], 0.0
            for l in ls[:-1]:
                acc += l / tot
                u.append(acc)
            return u

        ua = seg_cum_u(segs_a)
        ub = seg_cum_u(segs_b)
        na, nb = len(ca), len(cb)
        best_score, best_pairs = float("inf"), []
        gap = 0.25
        for shift in range(nb):
            cb_rot = cb[shift:] + cb[:shift]
            u0_b = ub[cb_rot[0][0]]
            u0_a = ua[ca[0][0]]
            dp = [[0.0] * (nb + 1) for _ in range(na + 1)]
            bt = [[0] * (nb + 1) for _ in range(na + 1)]
            for i in range(1, na + 1):
                dp[i][0] = i * gap; bt[i][0] = 1
            for j in range(1, nb + 1):
                dp[0][j] = j * gap; bt[0][j] = 2
            for i in range(1, na + 1):
                ia, aa = ca[i - 1]
                pos_a = (ua[ia] - u0_a) % 1.0
                for j in range(1, nb + 1):
                    ib, ab = cb_rot[j - 1]
                    pos_b = (ub[ib] - u0_b) % 1.0
                    d_pos = abs(pos_a - pos_b)
                    d_pos = min(d_pos, 1.0 - d_pos)
                    cost = d_pos * 2.0 + abs(aa - ab) * 0.2
                    m = dp[i - 1][j - 1] + cost
                    d1 = dp[i - 1][j] + gap
                    d2 = dp[i][j - 1] + gap
                    if m <= d1 and m <= d2:
                        dp[i][j] = m; bt[i][j] = 0
                    elif d1 <= d2:
                        dp[i][j] = d1; bt[i][j] = 1
                    else:
                        dp[i][j] = d2; bt[i][j] = 2
            if dp[na][nb] < best_score:
                best_score = dp[na][nb]
                pairs = []
                i, j = na, nb
                while i > 0 or j > 0:
                    if bt[i][j] == 0:
                        pairs.append((ca[i - 1][0], cb_rot[j - 1][0]))
                        i -= 1; j -= 1
                    elif bt[i][j] == 1:
                        i -= 1
                    else:
                        j -= 1
                pairs.reverse()
                best_pairs = pairs

        if len(best_pairs) >= 2:
            out = []
            k_n = len(best_pairs)
            for k in range(k_n):
                a0, b0 = best_pairs[k]
                a1, b1 = best_pairs[(k + 1) % k_n]
                sp_a = segs_a[a0:a1] if a1 > a0 else segs_a[a0:] + segs_a[:a1]
                sp_b = segs_b[b0:b1] if b1 > b0 else segs_b[b0:] + segs_b[:b1]
                if not sp_a or not sp_b:
                    continue
                out.extend(_morph_bezier_span(sp_a, sp_b, alpha))
            min_area = min(abs(_bezier_signed_area(segs_a)), abs(_bezier_signed_area(segs_b)))
            if out and abs(_bezier_signed_area(out)) >= 0.65 * min_area:
                return out

    return _morph_bezier_span(segs_a, segs_b, alpha)


def bezier_contours_to_svg_path(contours: list[list[tuple]], baseline: int) -> str:
    """Convert native Y-up cubic Bezier contours directly to clean Y-down SVG L/C paths."""
    parts = []
    for segs in contours:
        if not segs:
            continue
        p0 = segs[0][0]
        cmd = [f"M{round(p0[0], 1)},{round(baseline - p0[1], 1)}"]
        for s in segs:
            a, b, c, d = s
            if _seg_is_line(s, tol=0.5):
                cmd.append(f"L{round(d[0], 1)},{round(baseline - d[1], 1)}")
            else:
                cmd.append(
                    f"C{round(b[0], 1)},{round(baseline - b[1], 1)} "
                    f"{round(c[0], 1)},{round(baseline - c[1], 1)} "
                    f"{round(d[0], 1)},{round(baseline - d[1], 1)}"
                )
        cmd.append("Z")
        parts.append("".join(cmd))
    return " ".join(parts)


def _bezier_contour_self_intersects(segs: list[tuple]) -> bool:
    """Return True if a native cubic Bezier contour has any strict self-intersection."""
    pts = []
    for s in segs:
        p0, p1, p2, p3 = s
        n_sub = 1 if _seg_is_line(s, tol=0.5) else 4
        for k in range(n_sub):
            t = k / n_sub
            mt = 1.0 - t
            pt = (
                mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
            )
            if not pts or math.hypot(pt[0] - pts[-1][0], pt[1] - pts[-1][1]) > 0.5:
                pts.append(pt)
    if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 0.5:
        pts.pop()
    m = len(pts)
    if m < 4:
        return False

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        for j in range(i + 2, m):
            if i == 0 and j == m - 1:
                continue
            c, d = pts[j], pts[(j + 1) % m]
            if (orient(a, b, c) * orient(a, b, d) < -1e-6) and (orient(c, d, a) * orient(c, d, b) < -1e-6):
                return True
    return False


def style_transfer_bezier_contours(
    ba: list[list[tuple]],
    bb: list[list[tuple]],
    alpha: float = 0.5,
) -> list[list[tuple]]:
    """Native L/C style transfer: apply smooth 2D proportion warp directly to source Bezier control points."""
    all_a = [s[0] for c in ba for s in c]
    all_b = [s[0] for c in bb for s in c]
    ax0, ax1 = min(p[0] for p in all_a), max(p[0] for p in all_a)
    ay0, ay1 = min(p[1] for p in all_a), max(p[1] for p in all_a)
    bx0, bx1 = min(p[0] for p in all_b), max(p[0] for p in all_b)
    by0, by1 = min(p[1] for p in all_b), max(p[1] for p in all_b)
    aw, ah = max(ax1 - ax0, 1e-6), max(ay1 - ay0, 1e-6)
    bw, bh = max(bx1 - bx0, 1e-6), max(by1 - by0, 1e-6)
    acx = 0.5 * (ax0 + ax1)
    ay_mid = sum(p[1] for p in all_a) / len(all_a)
    by_mid = sum(p[1] for p in all_b) / len(all_b)

    sx = 1.0 + max(-0.15, min(0.15, (bw / aw - 1.0) * alpha * 0.35))
    ty0 = ay0 if abs(ay0) < 25.0 else ay0 + (by0 - ay0) * alpha * 0.4
    ty1 = ay1 + (by1 - ay1) * alpha * 0.4
    t_mid_shift = max(-0.08 * ah, min(0.08 * ah, (by_mid - ay_mid) * alpha * 0.4))

    def warp_pt(p):
        x, y = p
        nx = acx + (x - acx) * sx
        u = (y - ay0) / ah
        ny = ty0 + u * (ty1 - ty0) + 4.0 * u * (1.0 - u) * t_mid_shift
        return (nx, ny)

    return [[tuple(warp_pt(p) for p in s) for s in c] for c in ba]


def style_transfer_extend_bezier(
    root: ET.Element,
    transform=Identity,
    baseline: int = 800,
    sx: float = 1.0,
    tension: float = 1.0,
) -> tuple[str, tuple[float, float, float, float] | None]:
    """Native L/C style transfer for extended fallback glyphs: horizontal proportion + cubic handle tension."""
    contours = svg_to_bezier_contours(root, transform)
    if not contours:
        return "", None
    all_pts = [p for c in contours for s in c for p in (s[0], s[3])]
    x0, x1 = min(p[0] for p in all_pts), max(p[0] for p in all_pts)
    cx = 0.5 * (x0 + x1)

    out = []
    for c in contours:
        nc = []
        for s in c:
            p0, p1, p2, p3 = (
                (cx + (p[0] - cx) * sx, p[1]) for p in s
            )
            if tension != 1.0 and not _seg_is_line((p0, p1, p2, p3), tol=0.5):
                p1 = (p0[0] + (p1[0] - p0[0]) * tension, p0[1] + (p1[1] - p0[1]) * tension)
                p2 = (p3[0] + (p2[0] - p3[0]) * tension, p3[1] + (p2[1] - p3[1]) * tension)
            nc.append((p0, p1, p2, p3))
        out.append(nc)

    xs = [p[0] for c in out for s in c for p in (s[0], s[3])]
    ys = [p[1] for c in out for s in c for p in (s[0], s[3])]
    bounds = (min(xs), min(ys), max(xs), max(ys))
    return bezier_contours_to_svg_path(out, baseline), bounds


def morph_contours(
    root_a: ET.Element,
    root_b: ET.Element,
    transform_b=Identity,
    alpha: float = 0.5,
    n_samples: int = 144,
) -> list[list] | None:
    """Overlay root_b onto root_a and compute native Bezier-segment midpoint contours (with topology & self-intersection guards)."""
    ca = svg_to_contours(root_a)
    cb = svg_to_contours(root_b, transform_b)
    if not ca or not cb or len(ca) != len(cb):
        return None

    # Native Bezier-segment extraction (preserves exact L and C segments without polyline resampling)
    ba = svg_to_bezier_contours(root_a)
    bb = svg_to_bezier_contours(root_b, transform_b)
    if not ba or not bb or len(ba) != len(bb):
        return None

    # Automatic topology-mismatch guard: use native L/C style transfer instead of shape morphing
    if _max_chamfer_distance(ca, cb) > 0.09:
        return style_transfer_bezier_contours(ba, bb, alpha=alpha)

    all_a = [s[0] for c in ba for s in c]
    all_b = [s[0] for c in bb for s in c]
    ax = (min(p[0] for p in all_a) + max(p[0] for p in all_a)) * 0.5
    bx = (min(p[0] for p in all_b) + max(p[0] for p in all_b)) * 0.5
    dx = ax - bx
    bb_shifted = [[tuple((p[0] + dx, p[1]) for p in s) for s in c] for c in bb]

    def b_centroid(c):
        return (sum(s[0][0] for s in c) / len(c), sum(s[0][1] for s in c) / len(c))

    outer_sign_a = _bezier_signed_area(max(ba, key=lambda c: abs(_bezier_signed_area(c)))) > 0
    outer_sign_b = _bezier_signed_area(max(bb_shifted, key=lambda c: abs(_bezier_signed_area(c)))) > 0

    used_b: set[int] = set()
    morphed = []
    for a in ba:
        is_outer_a = (_bezier_signed_area(a) > 0) == outer_sign_a
        cx_a, cy_a = b_centroid(a)
        best_j, best_cost = None, float("inf")
        for j, b in enumerate(bb_shifted):
            if j in used_b:
                continue
            is_outer_b = (_bezier_signed_area(b) > 0) == outer_sign_b
            cx_b, cy_b = b_centroid(b)
            cost = (cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2 + (0 if is_outer_a == is_outer_b else 1e12)
            if cost < best_cost:
                best_cost, best_j = cost, j
        used_b.add(best_j)
        mc = morph_bezier_contour(a, bb_shifted[best_j], alpha)
        # Self-intersection & area-collapse guard per contour
        sa = abs(_bezier_signed_area(a))
        oa = abs(_bezier_signed_area(mc))
        if _bezier_contour_self_intersects(mc) or (sa > 500 and (oa < 0.60 * sa or oa > 1.65 * sa)):
            return style_transfer_bezier_contours(ba, bb, alpha=alpha)
        morphed.append(mc)
    return morphed


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
    if alpha1 < eps or alpha2 < eps or alpha1 > seg_len * 0.65 or alpha2 > seg_len * 0.65:
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


def contours_to_svg_path(contours: list[list], baseline: int) -> str:
    """Convert Y-up font contours (native Bezier segments or polylines) to a clean Y-down SVG path."""
    if contours and contours[0] and len(contours[0][0]) == 4:
        return bezier_contours_to_svg_path(contours, baseline)
    tol = 1.5 if baseline <= 1000 else 3.0
    parts = []
    for c in contours:
        if len(c) < 3:
            continue
        corners = [idx for idx, _ in detect_corners(c, angle_thresh=0.45, k=1)]
        if len(corners) == 0:
            i_min = min(range(len(c)), key=lambda i: c[i][1])
            i_max = max(range(len(c)), key=lambda i: c[i][1])
            corners = sorted({i_min, i_max})
        elif len(corners) == 1:
            opp = (corners[0] + len(c) // 2) % len(c)
            corners = sorted({corners[0], opp})

        num_c = len(corners)
        # First pass: extract spans and snap near-H/V straight spans consistently on shared corners
        corner_pts = [list(c[idx]) for idx in corners]
        spans: list[list[tuple[float, float]]] = []
        is_line: list[bool] = []
        for k in range(num_c):
            i0 = corners[k]
            i1 = corners[(k + 1) % num_c]
            span = c[i0:i1 + 1] if i1 > i0 else c[i0:] + c[:i1 + 1]
            spans.append(span)
            straight = len(span) >= 2 and _max_line_err(span) <= tol * 1.2
            is_line.append(straight)
            if straight:
                p0, p1 = span[0], span[-1]
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                if math.hypot(dx, dy) >= 1e-6:
                    ang_h = math.degrees(math.atan2(abs(dy), abs(dx)))
                    ang_v = math.degrees(math.atan2(abs(dx), abs(dy)))
                    if ang_h <= 3.5:
                        ym = 0.5 * (p0[1] + p1[1])
                        corner_pts[k][1] = ym
                        corner_pts[(k + 1) % num_c][1] = ym
                    elif ang_v <= 3.5:
                        xm = 0.5 * (p0[0] + p1[0])
                        corner_pts[k][0] = xm
                        corner_pts[(k + 1) % num_c][0] = xm

        start = corner_pts[0]
        seg = [f"M{round(start[0], 1)},{round(baseline - start[1], 1)}"]
        for k in range(num_c):
            p_start = (corner_pts[k][0], corner_pts[k][1])
            p_end = (corner_pts[(k + 1) % num_c][0], corner_pts[(k + 1) % num_c][1])
            span = spans[k]
            if len(span) < 2:
                continue
            if is_line[k]:
                seg.append(f"L{round(p_end[0], 1)},{round(baseline - p_end[1], 1)}")
                continue
            span = [p_start] + list(span[1:-1]) + [p_end]
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
