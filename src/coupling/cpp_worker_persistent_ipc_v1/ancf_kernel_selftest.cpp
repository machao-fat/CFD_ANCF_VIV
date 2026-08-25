#include "ancf_kernel.hpp"
#include "sha256.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

int main() {
  const std::vector<unsigned char> sha_probe{'a', 'b', 'c'};
  std::array<unsigned char, 32> sha_digest{};
  if (!cfd_ancf::wire::sha256_bytes(sha_probe, sha_digest) ||
      sha_digest != std::array<unsigned char, 32>{
          0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,
          0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad}) return 1;
  cfd_ancf::Model model;
  model.include_gravity = false; model.include_buoyancy = false;
  model.top_tension_N = 0.0;
  model.newton_tolerance = 1.0e-4;
  auto state = cfd_ancf::make_reference_state(model);
  auto force = std::vector<double>(3 * model.slices, 0.0);
  std::vector<double> internal;
  cfd_ancf::Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  double reference_force_max = 0.0;
  for (double value : internal) reference_force_max = std::max(reference_force_max, std::abs(value));
  if (reference_force_max > 1.0e-5) return 2;  // zero strain/curvature
  auto translated = state.q;
  for (std::size_t node = 0; node <= model.elements; ++node) translated[6 * node] += 0.37;
  cfd_ancf::internal_force_tangent(translated, model, internal, tangent);
  double translated_force_max = 0.0;
  for (double value : internal) translated_force_max = std::max(translated_force_max, std::abs(value));
  if (translated_force_max > 1.0e-5) return 2;  // rigid translation invariance
  auto rotated = state.q;
  const double angle = 0.31;
  const double sine = std::sin(angle), cosine = std::cos(angle);
  for (std::size_t node = 0; node <= model.elements; ++node) {
    const std::size_t base = 6 * node;
    const double s = state.q[base + 2];
    rotated[base] = sine * s;
    rotated[base + 2] = cosine * s;
    rotated[base + 3] = sine;
    rotated[base + 5] = cosine;
  }
  cfd_ancf::internal_force_tangent(rotated, model, internal, tangent);
  double rotated_force_max = 0.0;
  for (double value : internal) rotated_force_max = std::max(rotated_force_max, std::abs(value));
  if (rotated_force_max > 1.0e-4) return 2;  // rigid rotation invariance
  cfd_ancf::AssemblyTrace production_trace;
  std::vector<double> traced_force;
  cfd_ancf::Matrix traced_tangent;
  cfd_ancf::internal_force_tangent(state.q, model, traced_force, traced_tangent, &production_trace);
  const auto forensic = cfd_ancf::internal_force_forensic(state.q, model);
  if (production_trace.points.size() != model.elements * model.gauss_order ||
      traced_force != forensic.force || traced_tangent.data != forensic.tangent.data ||
      production_trace.points.size() != forensic.points.size() ||
      production_trace.element_force != forensic.element_force ||
      production_trace.global_force_after_element != forensic.global_force_after_element ||
      production_trace.element_tangent.size() != model.elements ||
      forensic.global_tangent_after_element.size() != model.elements) return 2;
  auto explicit_contract = model;
  explicit_contract.mass_gauss_order = 5;
  explicit_contract.fixed_dof = {0u, 1u, 2u, 6u * model.elements, 6u * model.elements + 1u};
  explicit_contract.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0};
  explicit_contract.boundary_contract_id = "ancf_v1_bottom_top_xy_zero";
  cfd_ancf::validate_model(explicit_contract);
  auto invalid_mass_rule = explicit_contract;
  invalid_mass_rule.mass_gauss_order = 7;
  try { cfd_ancf::validate_model(invalid_mass_rule); return 2; }
  catch (const std::invalid_argument&) {}
  auto invalid_boundary = explicit_contract;
  invalid_boundary.fixed_dof[1] = invalid_boundary.fixed_dof[0];
  try { cfd_ancf::validate_model(invalid_boundary); return 2; }
  catch (const std::invalid_argument&) {}
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
  auto malformed_force_state = cfd_ancf::make_reference_state(model);
  malformed_force_state.q[0] = std::numeric_limits<double>::quiet_NaN();
  try {
    std::vector<double> bad_force;
    cfd_ancf::Matrix bad_tangent;
    cfd_ancf::internal_force_tangent(malformed_force_state.q, model, bad_force, bad_tangent);
    return 4;
  } catch (const std::invalid_argument&) {
    // Public force/tangent evaluation must reject non-finite input.
  }
  auto excessive_newton = model;
  excessive_newton.max_newton = cfd_ancf::MAX_NEWTON + 1;
  try {
    cfd_ancf::validate_model(excessive_newton);
    return 4;
  } catch (const std::invalid_argument&) {
    // A malformed solver budget must fail before allocation or iteration.
  }
  auto nonmonotone_slices = model;
  nonmonotone_slices.slices = 3;
  nonmonotone_slices.slice_positions_m = {0.75, 0.25, 0.5};
  try {
    cfd_ancf::validate_model(nonmonotone_slices);
    return 4;
  } catch (const std::invalid_argument&) {
    // The C++ boundary must not rely on Python-side ordering checks.
  }
  auto wrong_slice_count = model;
  wrong_slice_count.slices = 3;
  wrong_slice_count.slice_positions_m = {0.25, 0.75};
  try {
    cfd_ancf::validate_model(wrong_slice_count);
    return 4;
  } catch (const std::invalid_argument&) {
    // Missing or extra mapping positions are a contract violation.
  }
  auto overflowing_load_state = cfd_ancf::make_reference_state(model);
  auto overflowing_force = force;
  overflowing_load_state.base_load[0] = std::numeric_limits<double>::max();
  overflowing_force[0] = std::numeric_limits<double>::max();
  try {
    (void)cfd_ancf::advance(overflowing_load_state, model, overflowing_force);
    return 4;
  } catch (const std::runtime_error&) {
    // Addition overflow must fail before the Newton scale is computed.
  }
  std::cout << "ancf_kernel_selftest=pass ndof=" << model.ndof() << " iterations=" << diagnostics.iterations << "," << loaded.iterations << "\n";
  return 0;
}
