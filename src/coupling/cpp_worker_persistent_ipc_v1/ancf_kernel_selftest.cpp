#include "ancf_kernel.hpp"

#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

int main() {
  cfd_ancf::Model model;
  model.include_gravity = false; model.include_buoyancy = false; model.top_tension_N = 0.0;
  model.newton_tolerance = 1.0e-4;
  auto state = cfd_ancf::make_reference_state(model);
  auto force = std::vector<double>(3 * model.slices, 0.0);
  std::vector<double> internal;
  cfd_ancf::Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  auto diagnostics = cfd_ancf::advance(state, model, force);
  if (!diagnostics.converged || !cfd_ancf::finite(state) || state.step != 1 || !std::isfinite(state.residual)) return 2;
  force[1] = 1.0e-3;
  auto loaded = cfd_ancf::advance(state, model, force);
  if (!loaded.converged || !cfd_ancf::finite(state) || state.step != 2 || !std::isfinite(loaded.residual)) return 3;
  auto constrained = cfd_ancf::make_reference_state(model);
  constrained.q[0] = 1.0;
  constrained.q[1] = -2.0;
  constrained.q[6 * model.elements] = 3.0;
  constrained.q[6 * model.elements + 1] = -4.0;
  (void)cfd_ancf::advance(constrained, model, force);
  if (constrained.q[0] != 0.0 || constrained.q[1] != 0.0 ||
      constrained.q[6 * model.elements] != 0.0 ||
      constrained.q[6 * model.elements + 1] != 0.0) return 3;
  auto scale_probe = cfd_ancf::make_reference_state(model);
  scale_probe.base_load[0] = 1.0e9;  // prescribed bottom reaction
  scale_probe.base_load[3] = 2.0;    // free translational load
  auto scale_diagnostics = cfd_ancf::advance(scale_probe, model, force);
  if (std::abs(scale_diagnostics.residual_scale - 2.0) > 1.0e-12) return 3;
  auto malformed_mass = cfd_ancf::make_reference_state(model);
  malformed_mass.mass = cfd_ancf::Matrix(1, 2);
  try {
    cfd_ancf::symmetrize_mass(malformed_mass);
    return 3;
  } catch (const std::invalid_argument&) {
    // expected: malformed public state must fail before indexing
  }
  for (int failure = 0; failure < 7; ++failure) {
    auto malformed = cfd_ancf::make_reference_state(model);
    auto malformed_force = force;
    if (failure == 0) malformed.qdot.clear();
    if (failure == 1) malformed.qddot[0] = std::numeric_limits<double>::quiet_NaN();
    if (failure == 2) malformed.base_load.pop_back();
    if (failure == 3) malformed.mass.rows = malformed.mass.cols = 0;
    if (failure == 4) malformed.time_s = -1.0;
    if (failure == 5) malformed_force[0] = std::numeric_limits<double>::quiet_NaN();
    if (failure == 6) malformed.step = (std::numeric_limits<std::size_t>::max)();
    try {
      (void)cfd_ancf::advance(malformed, model, malformed_force);
      return 4;
    } catch (const std::invalid_argument&) {
      // Every malformed state must fail before numerical assembly.
    }
  }
  std::cout << "ancf_kernel_selftest=pass ndof=" << model.ndof() << " iterations=" << diagnostics.iterations << "," << loaded.iterations << "\n";
  return 0;
}
