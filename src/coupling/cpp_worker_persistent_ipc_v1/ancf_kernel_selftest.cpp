#include "ancf_kernel.hpp"

#include <cmath>
#include <iostream>

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
  std::cout << "ancf_kernel_selftest=pass ndof=" << model.ndof() << " iterations=" << diagnostics.iterations << "," << loaded.iterations << "\n";
  return 0;
}
