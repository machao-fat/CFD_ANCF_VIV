#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr double kLengthM = 50.0;
constexpr double kPrecursorTerminalForceN = 1350.198335726;
constexpr double kTributaryLengthM = 50.0 / 3.0;
constexpr double kSliceForceN = kPrecursorTerminalForceN * kTributaryLengthM;
constexpr double kDtS = 0.005;
constexpr std::size_t kStepCount = 200;  // 1.0 s ANCF-only diagnostic.

void write_vector(std::ostream& out, const std::vector<double>& values) {
  out << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i != 0) out << ',';
    out << std::setprecision(17) << values[i];
  }
  out << ']';
}

cfd_ancf::Model model_contract() {
  cfd_ancf::Model model;
  model.length_m = kLengthM;
  model.diameter_m = 1.0;
  model.inner_diameter_m = 0.9;
  model.elements = 16;
  model.slices = 3;
  model.slice_positions_m = {50.0 / 6.0, 25.0, 250.0 / 6.0};
  model.top_tension_N = 2179104.0029808935;
  model.youngs_modulus_Pa = 3227125779.2218256;
  model.material_density = 26315.789473684214;
  model.fluid_density = 1000.0;
  model.gravity = 9.81;
  model.dt_s = kDtS;
  model.beta = 0.25;
  model.gamma = 0.5;
  model.max_newton = 40;
  model.newton_tolerance = 1.0e-8;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  model.damping_alpha = 0.0;
  model.damping_beta = 0.0;
  return model;
}

std::vector<double> slice_force_contract(const cfd_ancf::Model& model) {
  std::vector<double> force(3u * model.slices, 0.0);
  for (std::size_t slice = 0; slice < model.slices; ++slice) force[3u * slice] = kSliceForceN;
  return force;
}

std::vector<double> position_at(const cfd_ancf::Model& model, const std::vector<double>& q, double s) {
  const double le = model.length_m / static_cast<double>(model.elements);
  const std::size_t element = s == model.length_m ? model.elements - 1u :
      std::min(model.elements - 1u, static_cast<std::size_t>(std::floor(s / le)));
  const double r = (s - static_cast<double>(element) * le) / le;
  const double n[4] = {1.0 - 3.0 * r * r + 2.0 * r * r * r,
                       le * (r - 2.0 * r * r + r * r * r),
                       3.0 * r * r - 2.0 * r * r * r,
                       le * (-r * r + r * r * r)};
  std::vector<double> value(3u, 0.0);
  const std::size_t base = 6u * element;
  for (std::size_t node = 0; node < 4u; ++node)
    for (std::size_t component = 0; component < 3u; ++component)
      value[component] += n[node] * q[base + 3u * node + component];
  return value;
}

double free_residual_inf(const cfd_ancf::State& state, const cfd_ancf::Model& model,
                         const std::vector<double>& load) {
  std::vector<double> internal;
  cfd_ancf::Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  const std::vector<std::size_t> fixed = {0u, 1u, 2u, 6u * model.elements, 6u * model.elements + 1u};
  double result = 0.0;
  for (std::size_t dof = 0; dof < model.ndof(); ++dof) {
    if (std::find(fixed.begin(), fixed.end(), dof) == fixed.end())
      result = std::max(result, std::abs(internal[dof] - load[dof]));
  }
  return result;
}

double max_delta_x(const cfd_ancf::Model& model, const cfd_ancf::State& no_flow,
                   const cfd_ancf::State& mean_drag) {
  double result = 0.0;
  for (std::size_t sample = 0; sample <= 1600u; ++sample) {
    const double s = model.length_m * static_cast<double>(sample) / 1600.0;
    result = std::max(result, std::abs(position_at(model, mean_drag.q, s)[0] -
                                       position_at(model, no_flow.q, s)[0]));
  }
  return result;
}

void write_sample(std::ostream& out, const cfd_ancf::Model& model, const cfd_ancf::State& state,
                  const cfd_ancf::State& no_flow, bool& first) {
  if (!first) out << ',';
  first = false;
  double maximum_ux = 0.0, maximum_vx = 0.0;
  for (std::size_t sample = 0; sample <= 1600u; ++sample) {
    const double s = model.length_m * static_cast<double>(sample) / 1600.0;
    maximum_ux = std::max(maximum_ux, std::abs(position_at(model, state.q, s)[0] -
                                                position_at(model, no_flow.q, s)[0]));
    maximum_vx = std::max(maximum_vx, std::abs(position_at(model, state.qdot, s)[0]));
  }
  out << "{\"time_s\":" << std::setprecision(17) << state.time_s
      << ",\"max_abs_ux_m\":" << maximum_ux << ",\"max_abs_vx_mps\":" << maximum_vx
      << ",\"slices\":[";
  for (std::size_t slice = 0; slice < model.slices; ++slice) {
    if (slice != 0) out << ',';
    const double s = model.slice_positions_m[slice];
    const auto position = position_at(model, state.q, s);
    const auto velocity = position_at(model, state.qdot, s);
    const auto acceleration = position_at(model, state.qddot, s);
    const auto reference = position_at(model, no_flow.q, s);
    out << "{\"slice_id\":" << slice << ",\"ux_m\":" << position[0] - reference[0]
        << ",\"uy_m\":" << position[1] - reference[1] << ",\"vx_mps\":" << velocity[0]
        << ",\"vy_mps\":" << velocity[1] << ",\"ax_mps2\":" << acceleration[0]
        << ",\"ay_mps2\":" << acceleration[1] << '}';
  }
  out << "]}";
}

}  // namespace

// Diagnostic-only C++ ANCF study. No OpenFOAM, preCICE, MATLAB, or worker IPC
// is started. It calls the production C++ kernel's static and transient paths.
int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: cfd_ancf_mean_drag_initialization_diagnostic <output.json>\n";
    return 2;
  }
  try {
    const auto model = model_contract();
    cfd_ancf::validate_model(model);
    const auto slice_force = slice_force_contract(model);
    const auto mapped = cfd_ancf::external_force(model, slice_force);
    const auto base = cfd_ancf::static_base_load(model);
    std::vector<double> mean_load = base;
    for (std::size_t dof = 0; dof < mean_load.size(); ++dof) mean_load[dof] += mapped[dof];

    auto no_flow = cfd_ancf::make_reference_state(model);
    const auto no_flow_diag = cfd_ancf::static_equilibrium(no_flow, model, base, 40u, 0.8);
    auto mean_drag = cfd_ancf::make_reference_state(model);
    const auto mean_drag_diag = cfd_ancf::static_equilibrium(mean_drag, model, mean_load, 40u, 0.8);
    const double no_flow_residual = free_residual_inf(no_flow, model, base);
    const double mean_drag_residual = free_residual_inf(mean_drag, model, mean_load);

    auto step = no_flow;
    step.base_load = base;
    double max_step_ux = 0.0, max_step_vx = 0.0;
    std::ofstream out(argv[1], std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("cannot write output");
    out << std::setprecision(17);
    out << "{\"schema_version\":\"ancf-mean-drag-initialization-diagnostic-v1\""
        << ",\"mode\":\"ANCF_only\",\"dt_s\":" << model.dt_s
        << ",\"duration_s\":" << kStepCount * model.dt_s
        << ",\"steps\":" << kStepCount
        << ",\"slice_force_x_N\":" << kSliceForceN
        << ",\"slice_force_representation\":\"integrated_slice_force_N\""
        << ",\"slice_force\":";
    write_vector(out, slice_force);
    out << ",\"mapped_generalized_force\":";
    write_vector(out, mapped);
    out << ",\"no_flow_static\":{\"iterations\":" << no_flow_diag.iterations
        << ",\"residual\":" << no_flow_residual << ",\"q\":";
    write_vector(out, no_flow.q);
    out << "},\"mean_drag_static\":{\"iterations\":" << mean_drag_diag.iterations
        << ",\"residual\":" << mean_drag_residual << ",\"q\":";
    write_vector(out, mean_drag.q);
    out << ",\"max_abs_ux_m\":" << max_delta_x(model, no_flow, mean_drag) << ",\"slices\":[";
    for (std::size_t slice = 0; slice < model.slices; ++slice) {
      if (slice != 0) out << ',';
      const auto a = position_at(model, no_flow.q, model.slice_positions_m[slice]);
      const auto b = position_at(model, mean_drag.q, model.slice_positions_m[slice]);
      out << "{\"slice_id\":" << slice << ",\"s_ref_m\":" << model.slice_positions_m[slice]
          << ",\"ux_m\":" << b[0] - a[0] << ",\"uy_m\":" << b[1] - a[1] << '}';
    }
    out << "]},\"step_load\":{\"samples\":[";
    bool first = true;
    for (std::size_t record = 0; record <= kStepCount; ++record) {
      write_sample(out, model, step, no_flow, first);
      for (std::size_t sample = 0; sample <= 1600u; ++sample) {
        const double s = model.length_m * static_cast<double>(sample) / 1600.0;
        max_step_ux = std::max(max_step_ux, std::abs(position_at(model, step.q, s)[0] - position_at(model, no_flow.q, s)[0]));
        max_step_vx = std::max(max_step_vx, std::abs(position_at(model, step.qdot, s)[0]));
      }
      if (record != kStepCount) (void)cfd_ancf::advance(step, model, slice_force);
    }
    out << "],\"max_abs_ux_m\":" << max_step_ux << ",\"max_abs_vx_mps\":" << max_step_vx
        << ",\"finite\":" << (cfd_ancf::finite(step) ? "true" : "false") << "}}\n";
    if (!out) throw std::runtime_error("output write failure");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ancf_mean_drag_initialization_diagnostic_error=" << error.what() << '\n';
    return 3;
  }
}
