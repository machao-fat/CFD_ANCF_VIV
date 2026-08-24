"""Validated Newmark average-acceleration runner for a transverse SDOF.

The mass ratio follows the common displaced-fluid definition
    m* = m / (rho*pi*D**2/4)
and Ur = U/(fn*D).  The supplied hydrodynamic force is a total force for a
unit span.  Predictor and corrector operate on copies, so the predictor never
overwrites the converged state.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SDOFParameters:
    rho: float
    diameter: float
    flow_speed: float
    mass_ratio: float
    reduced_velocity: float
    damping_ratio: float
    dt: float

    @property
    def displaced_mass(self) -> float:
        return self.rho * math.pi * self.diameter**2 / 4.0

    @property
    def mass(self) -> float:
        return self.mass_ratio * self.displaced_mass

    @property
    def natural_frequency_hz(self) -> float:
        return self.flow_speed / (self.reduced_velocity * self.diameter)

    @property
    def omega_n(self) -> float:
        return 2.0 * math.pi * self.natural_frequency_hz

    @property
    def stiffness(self) -> float:
        return self.mass * self.omega_n**2

    @property
    def damping(self) -> float:
        return 2.0 * self.damping_ratio * self.mass * self.omega_n

    def as_dict(self) -> dict[str, float]:
        return {
            "rho": self.rho,
            "diameter": self.diameter,
            "flow_speed": self.flow_speed,
            "mass_ratio": self.mass_ratio,
            "reduced_velocity": self.reduced_velocity,
            "damping_ratio": self.damping_ratio,
            "dt": self.dt,
            "displaced_mass": self.displaced_mass,
            "mass": self.mass,
            "natural_frequency_hz": self.natural_frequency_hz,
            "stiffness": self.stiffness,
            "damping": self.damping,
        }


@dataclass
class SDOFState:
    y: float = 0.0
    v: float = 0.0
    a: float = 0.0
    step: int = 0
    time_s: float = 0.0


class SDOFRunner:
    """One-pass predictor/corrector for m*y''+c*y'+k*y=Fy."""

    def __init__(self, parameters: SDOFParameters) -> None:
        self.parameters = parameters
        self.state = SDOFState()
        self._predicted: SDOFState | None = None

    def initialize(self, *, y: float = 0.0, v: float = 0.0, step: int = 0, time_s: float = 0.0) -> None:
        p = self.parameters
        a = (0.0 - p.damping * v - p.stiffness * y) / p.mass
        self.state = SDOFState(y=y, v=v, a=a, step=step, time_s=time_s)
        self._predicted = None

    def restore(self, state: SDOFState) -> None:
        """Restore an exactly converged state from a synchronized checkpoint.

        ``initialize`` intentionally recomputes acceleration for a zero applied
        load and is therefore not suitable for a CFD restart.  A restart must
        preserve the converged displacement, velocity *and* acceleration that
        were written at the same physical time as the OpenFOAM fields.
        """
        values = (state.y, state.v, state.a, state.time_s)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("checkpoint state contains NaN/Inf")
        if state.step < 0:
            raise ValueError("checkpoint step must be non-negative")
        expected_time = state.step * self.parameters.dt
        if abs(state.time_s - expected_time) > 1.0e-9 * max(1.0, abs(expected_time)):
            raise ValueError("checkpoint time does not match step and dt")
        self.state = SDOFState(**vars(state))
        self._predicted = None

    def _advance(self, old: SDOFState, force: float, step: int, time_s: float) -> SDOFState:
        p = self.parameters
        dt = p.dt
        beta = 0.25
        gamma = 0.5
        y_hat = old.y + dt * old.v + dt * dt * (0.5 - beta) * old.a
        v_hat = old.v + dt * (1.0 - gamma) * old.a
        effective = p.mass + gamma * dt * p.damping + beta * dt * dt * p.stiffness
        a = (force - p.damping * v_hat - p.stiffness * y_hat) / effective
        y = y_hat + beta * dt * dt * a
        v = v_hat + gamma * dt * a
        return SDOFState(y=y, v=v, a=a, step=step, time_s=time_s)

    def predict(self, step: int, time_s: float, previous_force: float) -> SDOFState:
        if step != self.state.step + 1:
            raise ValueError(f"predict step {step} is not after state step {self.state.step}")
        if abs(time_s - step * self.parameters.dt) > 1.0e-9 * max(1.0, abs(time_s)):
            raise ValueError("predict time does not match dt and step")
        self._predicted = self._advance(self.state, previous_force, step, time_s)
        return SDOFState(**vars(self._predicted))

    def correct(self, step: int, time_s: float, force: float) -> tuple[SDOFState, dict[str, float]]:
        if self._predicted is None or step != self._predicted.step:
            raise ValueError("correct requires the matching predictor")
        corrected = self._advance(self.state, force, step, time_s)
        prediction = self._predicted
        self.state = corrected
        self._predicted = None
        audit = {
            "predictor_displacement_residual_m": corrected.y - prediction.y,
            "predictor_velocity_residual_mps": corrected.v - prediction.v,
            "kinetic_energy_J": 0.5 * self.parameters.mass * corrected.v**2,
            "spring_energy_J": 0.5 * self.parameters.stiffness * corrected.y**2,
            "damping_power_W": self.parameters.damping * corrected.v**2,
            "mechanical_energy_J": 0.5 * self.parameters.mass * corrected.v**2 + 0.5 * self.parameters.stiffness * corrected.y**2,
        }
        return SDOFState(**vars(corrected)), audit

    def get_motion(self) -> dict[str, float]:
        s = self.state
        return {"y_m": s.y, "vy_mps": s.v, "ay_mps2": s.a, "step": s.step, "time_s": s.time_s}
