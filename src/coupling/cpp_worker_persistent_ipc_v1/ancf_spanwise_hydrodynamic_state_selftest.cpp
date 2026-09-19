#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using cfd_ancf::Matrix;
using cfd_ancf::Model;
using cfd_ancf::State;

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

bool exactly_equal(const Matrix& left, const Matrix& right) {
  return left.rows == right.rows && left.cols == right.cols && left.data == right.data;
}

double max_abs_difference(const Matrix& left, const Matrix& right) {
  require(left.rows == right.rows && left.cols == right.cols, "matrix dimensions differ");
  double maximum = 0.0;
  for (std::size_t i = 0; i < left.data.size(); ++i)
    maximum = std::max(maximum, std::abs(left.data[i] - right.data[i]));
  return maximum;
}

Matrix add(const Matrix& left, const Matrix& right) {
  require(left.rows == right.rows && left.cols == right.cols, "matrix addition dimensions differ");
  Matrix result(left.rows, left.cols);
  for (std::size_t i = 0; i < result.data.size(); ++i) result.data[i] = left.data[i] + right.data[i];
  return result;
}

Matrix scale(const Matrix& input, double factor) {
  Matrix result(input.rows, input.cols);
  for (std::size_t i = 0; i < result.data.size(); ++i) result.data[i] = factor * input.data[i];
  return result;
}

bool zero(const Matrix& matrix) {
  return std::all_of(matrix.data.begin(), matrix.data.end(),
                     [](double value) { return value == 0.0; });
}

Model control_model() {
  Model model;
  model.length_m = 8.0;
  model.elements = 4;
  model.slices = 3;
  model.slice_positions_m = {2.0, 4.0, 6.0};
  model.top_tension_N = 0.0;
  model.newton_tolerance = 1.0e-8;
  model.max_newton = 80;
  model.dt_s = 2.5e-4;
  model.include_gravity = true;
  model.include_buoyancy = true;
  return model;
}

Model hydro_model() {
  Model model = control_model();
  model.hydrodynamic_regions = {
      {0.0, 4.0, {25.0, 25.0, 25.0}, {0.0, 3.0, 0.0}},
      {4.0, 8.0, {25.0, 25.0, 25.0}, {0.0, 3.0, 0.0}},
  };
  return model;
}

}  // namespace

int main() {
  try {
    const Model legacy_model = control_model();
    const State legacy = cfd_ancf::make_reference_state(legacy_model);
    const Matrix zero_hydro_mass = cfd_ancf::assemble_spanwise_added_mass(legacy_model, {});
    const Matrix zero_hydro_damping = cfd_ancf::assemble_spanwise_linear_damping(legacy_model, {});
    require(zero(zero_hydro_mass) && zero(zero_hydro_damping), "empty SHM1 assembler regression failed");
    require(exactly_equal(legacy.mass, cfd_ancf::resolve_total_mass(legacy_model, legacy.mass)),
            "legacy total mass is not exact");
    require(zero(legacy.damping), "legacy State damping changed");

    Model hydro = hydro_model();
    const Matrix structural_mass = legacy.mass;
    const Matrix Mh = cfd_ancf::assemble_spanwise_added_mass(hydro, hydro.hydrodynamic_regions);
    const Matrix Ch = cfd_ancf::assemble_spanwise_linear_damping(hydro, hydro.hydrodynamic_regions);
    const State hydro_state = cfd_ancf::make_reference_state(hydro);
    require(max_abs_difference(hydro_state.mass, add(structural_mass, Mh)) == 0.0,
            "canonical mass is not M_base + Mh");
    require(exactly_equal(hydro_state.damping, Ch) && !zero(Ch),
            "hydro-only damping is not Ch");

    const Matrix full_mass = cfd_ancf::assemble_spanwise_added_mass(
        legacy_model, {{0.0, legacy_model.length_m,
                        {legacy_model.mass_per_length(), legacy_model.mass_per_length(),
                         legacy_model.mass_per_length()},
                        {0.0, 0.0, 0.0}}});
    require(max_abs_difference(full_mass, structural_mass) <= 2.0e-12,
            "full-span known added mass is not the structural mass oracle");
    Model double_mass = legacy_model;
    double_mass.hydrodynamic_regions = {{0.0, double_mass.length_m,
        {double_mass.mass_per_length(), double_mass.mass_per_length(), double_mass.mass_per_length()},
        {0.0, 0.0, 0.0}}};
    const State doubled = cfd_ancf::make_reference_state(double_mass);
    require(max_abs_difference(doubled.mass, scale(structural_mass, 2.0)) <= 2.0e-12,
            "full-span known mass scaling is not two times structural mass");

    Model rayleigh = hydro;
    rayleigh.damping_alpha = 0.125;
    rayleigh.damping_beta = 0.0;
    const Matrix Cr = cfd_ancf::resolve_rayleigh_damping(rayleigh, hydro_state.mass, hydro_state.q, false);
    const Matrix Ct = cfd_ancf::resolve_total_damping(rayleigh, hydro_state.mass, hydro_state.q, false);
    require(max_abs_difference(Cr, scale(hydro_state.mass, rayleigh.damping_alpha)) == 0.0,
            "mass proportional Rayleigh damping did not use M_total");
    require(max_abs_difference(Ct, add(Cr, Ch)) == 0.0,
            "total damping is not C_R + Ch");

    std::cerr << "m3_state_selftest_phase=static\n";
    State static_legacy = cfd_ancf::make_reference_state(legacy_model);
    State static_hydro = cfd_ancf::make_reference_state(hydro);
    const auto base = cfd_ancf::static_base_load(legacy_model);
    const auto legacy_static = cfd_ancf::static_equilibrium(static_legacy, legacy_model, base, 8, 0.8);
    const auto hydro_static = cfd_ancf::static_equilibrium(static_hydro, hydro, base, 8, 0.8);
    require(legacy_static.converged && hydro_static.converged && static_legacy.q == static_hydro.q,
            "SHM1 changed static equilibrium");

    // The original hand-prescribed sine/slope free-vibration gate was
    // invalidated by the M3 forensic as TEST_CONSTRUCTION_DEFECT.  It is
    // intentionally not retained as a permanent qualification gate.  The
    // valid static-equilibrium/eigenmode/modal-perturbation evidence is the
    // external M3 replacement package, which must remain linked from the M3
    // final report rather than duplicated here.

    std::cout << "{\"status\":\"pass\",\"canonical_mass\":true,"
                 "\"full_span_mass_scaling\":true,\"hydro_only_damping\":true,"
                 "\"rayleigh_total_mass\":true,\"total_damping\":true,"
                 "\"static_unaffected\":true,\"invalid_free_vibration_gate_removed\":true}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "M3 state selftest failure: " << error.what() << '\n';
    return 1;
  }
}
