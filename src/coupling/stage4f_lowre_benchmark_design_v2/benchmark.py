"""Frozen constants and analytic prechecks for Stage 4F-A-v2."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


MASS_RATIOS = (2, 5, 10)
BETAS = (0.001, 0.01, 0.05)
ADMISSIBLE_BETAS = (0.01, 0.05)
SLICE_COUNTS = (3, 5, 9)
ST_VALUES = (0.15, 0.18)
CL_AMPLITUDES = (0.1, 0.3)
VIRTUAL_WORK_TOLERANCE = 1.0e-12


@dataclass(frozen=True)
class LowReContract:
    D_m: float = 1.0
    U_mps: float = 1.0
    rho_kgpm3: float = 1000.0
    nu_m2ps: float = 0.01
    L_m: float = 50.0
    d_inner_over_D: float = 0.9
    added_mass_coefficient: float = 1.0
    damping_ratio: float = 0.01
    Ur1_target: float = 5.5

    @property
    def d_inner_m(self) -> float:
        return self.d_inner_over_D * self.D_m

    @property
    def reynolds_number(self) -> float:
        return self.U_mps * self.D_m / self.nu_m2ps

    @property
    def slenderness_ratio(self) -> float:
        return self.L_m / self.D_m

    @property
    def target_wet_frequency_Hz(self) -> float:
        return self.U_mps / (self.Ur1_target * self.D_m)

    @property
    def area_m2(self) -> float:
        return math.pi * (self.D_m**2 - self.d_inner_m**2) / 4.0

    @property
    def second_moment_m4(self) -> float:
        return math.pi * (self.D_m**4 - self.d_inner_m**4) / 64.0

    @property
    def displaced_mass_kgpm(self) -> float:
        return self.rho_kgpm3 * math.pi * self.D_m**2 / 4.0

    @property
    def added_mass_kgpm(self) -> float:
        return self.added_mass_coefficient * self.displaced_mass_kgpm

    def t_over_ea(self, beta: float) -> float:
        return self.second_moment_m4 / (float(beta) * self.L_m**2 * self.area_m2)

    def mass_candidate(self, mass_ratio: int) -> dict[str, float | int | str]:
        if mass_ratio not in MASS_RATIOS:
            raise ValueError("mass ratio is outside the frozen candidate set")
        structural = float(mass_ratio) * self.displaced_mass_kgpm
        effective = structural + self.added_mass_kgpm
        return {
            "mass_ratio": mass_ratio,
            "m_f_kgpm": self.displaced_mass_kgpm,
            "m_s_kgpm": structural,
            "m_added_kgpm": self.added_mass_kgpm,
            "m_eff_kgpm": effective,
            "equivalent_structure_density_kgpm3": structural / self.area_m2,
            "mass_matrix_construction": (
                "consistent Hermite M_structure plus consistent transverse "
                "Hermite M_added; no dry-frequency multiplier"
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "stage4f-a-v2-low-re-contract-1.0",
            "methodology_identity": "low_re_standard_benchmark_v2_not_vivdatashare",
            "D_m": self.D_m,
            "U_mps": self.U_mps,
            "rho_kgpm3": self.rho_kgpm3,
            "nu_m2ps": self.nu_m2ps,
            "Re": self.reynolds_number,
            "L_m": self.L_m,
            "L_over_D": self.slenderness_ratio,
            "d_inner_m": self.d_inner_m,
            "d_inner_over_D": self.d_inner_over_D,
            "area_m2": self.area_m2,
            "second_moment_m4": self.second_moment_m4,
            "I_over_A_m2": self.second_moment_m4 / self.area_m2,
            "Ca": self.added_mass_coefficient,
            "damping_ratio": self.damping_ratio,
            "Ur1_target": self.Ur1_target,
            "Ur1_allowed_range": [5.0, 6.0],
            "f1_wet_target_Hz": self.target_wet_frequency_Hz,
            "St_diagnostic_values": list(ST_VALUES),
            "reference_shedding_frequency_Hz": [
                value * self.U_mps / self.D_m for value in ST_VALUES
            ],
            "reference_frequency_is_coupled_frequency": False,
            "openfoam_started": False,
        }


def corrected_beta_screen(contract: LowReContract | None = None) -> dict[str, Any]:
    contract = contract or LowReContract()
    candidates = []
    for beta in BETAS:
        ratio = contract.t_over_ea(beta)
        candidates.append(
            {
                "beta": beta,
                "T_over_EA": ratio,
                "T_over_EA_percent": 100.0 * ratio,
                "threshold": 0.01,
                "passes": ratio <= 0.01,
            }
        )
    return {
        "schema_version": "stage4f-a-v2-beta-screen-1.0",
        "formula": "T/EA = I/(beta*L^2*A)",
        "independently_recomputed": True,
        "L_m": contract.L_m,
        "area_m2": contract.area_m2,
        "second_moment_m4": contract.second_moment_m4,
        "candidates": candidates,
        "accepted_betas": [item["beta"] for item in candidates if item["passes"]],
        "rejected_betas": [item["beta"] for item in candidates if not item["passes"]],
        "matches_expected_gate_pattern": [item["passes"] for item in candidates]
        == [False, True, True],
    }


def uniform_slice_geometry(count: int, length_m: float = 50.0) -> tuple[list[float], list[float]]:
    if count not in SLICE_COUNTS:
        raise ValueError("slice count is outside the frozen set")
    boundaries = [length_m * index / count for index in range(count + 1)]
    centers = [(boundaries[index] + boundaries[index + 1]) / 2.0 for index in range(count)]
    return boundaries, centers


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_records(paths: Iterable[Path], root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted({item.resolve() for item in paths}, key=lambda item: item.as_posix()):
        if path.is_file():
            records.append(
                {
                    "path": path.relative_to(root.resolve()).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return records


def combined_record_hash(records: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_json_bytes(list(records))).hexdigest()


def all_finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(all_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(all_finite(item) for item in value)
    return True

