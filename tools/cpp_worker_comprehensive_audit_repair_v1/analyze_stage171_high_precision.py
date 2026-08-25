"""Offline high-precision ANCF force reference for Stage171 diagnosis."""
from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np

Real = np.longdouble

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = next((ROOT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1").rglob("cpp_input_fixture_step559.json"))
GOLDEN = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage169_dot_right_replay/forensic_step560.json"
GOLDEN_JSONL = next((ROOT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1").rglob("matlab_step559_599_golden.jsonl"))


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]


def transpose(a):
    return [list(x) for x in zip(*a)]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def scale(a, s):
    return [x * s for x in a]


def outer(a, b):
    return [[x * y for y in b] for x in a]


def m_add(*values):
    out = [[Real(0) for _ in values[0][0]] for _ in values[0]]
    for value in values:
        out = [[out[i][j] + value[i][j] for j in range(len(out[0]))] for i in range(len(out))]
    return out


def m_scale(a, s):
    return [[x * s for x in row] for row in a]


def cross_matrix(a):
    return [[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]]


def shape(x, length, derivative):
    xi = x / length
    xi2 = xi ** 2
    xi3 = xi ** 3
    length2 = length ** 2
    if derivative == 1:
        return [(6 * xi2 - 6 * xi) / length, 1 - 4 * xi + 3 * xi2,
                (-6 * xi2 + 6 * xi) / length, -2 * xi + 3 * xi2]
    if derivative == 2:
        return [(12 * xi - 6) / length2, (-4 + 6 * xi) / length,
                (6 - 12 * xi) / length2, (-2 + 6 * xi) / length]
    raise ValueError(derivative)


def block(s):
    out = [[Real(0) for _ in range(12)] for _ in range(3)]
    for b in range(4):
        for i in range(3):
            out[i][3 * b + i] = s[b]
    return out


def force(q, model):
    length = Real(str(model["length_m"]))
    elements = int(model["elements"])
    le = length / elements
    E = Real(str(model["youngs_modulus_Pa"]))
    D = Real(str(model["diameter_m"]))
    d = Real(str(model["inner_diameter_m"]))
    pi = Real(str(np.pi))
    area = pi * (D * D - d * d) / 4
    ea = E * area
    ei = E * pi * (D ** 4 - d ** 4) / 64
    xi = [-Real(np.sqrt(Real(5) + 2 * np.sqrt(Real(10) / 7))) / 3,
          -Real(np.sqrt(Real(5) - 2 * np.sqrt(Real(10) / 7))) / 3, Real(0),
          Real(np.sqrt(Real(5) - 2 * np.sqrt(Real(10) / 7))) / 3,
          Real(np.sqrt(Real(5) + 2 * np.sqrt(Real(10) / 7))) / 3]
    weights = [(Real(322) - 13 * np.sqrt(Real(70))) / 900, (Real(322) + 13 * np.sqrt(Real(70))) / 900,
               Real(128) / 225, (Real(322) + 13 * np.sqrt(Real(70))) / 900,
               (Real(322) - 13 * np.sqrt(Real(70))) / 900]
    out = [Real(0) for _ in q]
    for element in range(elements):
        qe = q[6 * element:6 * element + 12]
        fe = [Real(0) for _ in range(12)]
        for xref, weight in zip(xi, weights):
            x = (xref + 1) * le / 2
            B = block(shape(x, le, 1)); C = block(shape(x, le, 2))
            a = [sum(B[i][j] * qe[j] for j in range(12)) for i in range(3)]
            b = [sum(C[i][j] * qe[j] for j in range(12)) for i in range(3)]
            a2 = dot(a, a); v = cross(a, b); v2 = dot(v, v)
            Xa = cross_matrix(a); Xb = cross_matrix(b); Xv = cross_matrix(v)
            inv3 = a2 ** -3; inv4 = a2 ** -4; inv5 = a2 ** -5
            eye = [[Real(1) if i == j else Real(0) for j in range(3)] for i in range(3)]
            ga_b = add(scale([sum(Xb[i][k] * v[k] for k in range(3)) for i in range(3)], inv3),
                       scale(a, -3 * v2 * inv4))
            gb_b = scale([sum(Xa[i][k] * v[k] for k in range(3)) for i in range(3)], -inv3)
            Haa_b = m_add(m_scale(matmul(Xb, Xb), -inv3),
                          m_scale(outer([sum(Xb[i][k] * v[k] for k in range(3)) for i in range(3)], a), -6 * inv4),
                          m_scale(outer(a, [sum(Xb[i][k] * v[k] for k in range(3)) for i in range(3)]), -3 * inv4),
                          m_scale(outer(a, a), 24 * v2 * inv5),
                          m_scale(eye, -3 * v2 * inv4))
            Hab = m_add(m_scale(m_add(m_scale(Xv, -1), matmul(Xb, Xa)), inv3),
                        m_scale(outer(a, [sum(Xa[i][k] * v[k] for k in range(3)) for i in range(3)]), 3 * inv4))
            Hbb = m_scale(matmul(Xa, Xa), -inv3)
            eps = (a2 - 1) / 2
            ga = add(scale(a, ea * eps), scale(ga_b, ei)); gb = scale(gb_b, ei)
            Haa = m_add(m_scale(m_add(outer(a, a), m_scale(eye, eps)), ea), m_scale(Haa_b, ei))
            Hab = m_scale(Hab, ei); Hbb = m_scale(Hbb, ei)
            Bt = transpose(B); Ct = transpose(C)
            bga = [sum(Bt[i][c] * ga[c] for c in range(3)) for i in range(12)]
            cgb = [sum(Ct[i][c] * gb[c] for c in range(3)) for i in range(12)]
            factor = weight * le / 2
            fe = [fe[i] + (bga[i] + cgb[i]) * factor for i in range(12)]
        for i in range(12):
            out[6 * element + i] += fe[i]
    return out


def main():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN_JSONL.read_text(encoding="utf-8").splitlines()[0])
    q = [Real(str(x)) for x in golden["q"]]
    ref = [Real(str(x)) for x in golden["internal_force"]]
    candidate = force(q, fixture)
    errors = [abs(a - b) for a, b in zip(candidate, ref)]
    print(json.dumps({"max_abs_high_precision_minus_matlab": float(max(errors)),
                      "index": errors.index(max(errors)),
                      "matlab": float(ref[errors.index(max(errors))]),
                      "high_precision": float(candidate[errors.index(max(errors))])}, indent=2))


if __name__ == "__main__":
    main()
