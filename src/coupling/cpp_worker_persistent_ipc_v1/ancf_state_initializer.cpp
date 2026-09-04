#include "ancf_kernel.hpp"
#include "sha256.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <vector>

namespace {
std::string hex(const std::array<unsigned char, 32>& digest) {
  std::ostringstream out;
  out << std::hex << std::setfill('0');
  for (unsigned char value : digest) out << std::setw(2) << static_cast<unsigned>(value);
  return out.str();
}

template <class T>
void append_bytes(std::vector<unsigned char>& output, const T& value) {
  const auto* begin = reinterpret_cast<const unsigned char*>(&value);
  output.insert(output.end(), begin, begin + sizeof(T));
}

void write_array(std::ostream& out, const std::vector<double>& values) {
  out << '[' << std::setprecision(17);
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i != 0) out << ',';
    out << values[i];
  }
  out << ']';
}

bool finite_matrix(const cfd_ancf::Matrix& value) {
  return value.rows == value.cols && value.data.size() == value.rows * value.cols &&
      std::all_of(value.data.begin(), value.data.end(), [](double item) { return std::isfinite(item); });
}
}

// Offline-only C++ initializer. It uses the production kernel reference-state
// constructor and never starts MATLAB, OpenFOAM, WSL, or CFD.
int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: cfd_ancf_cpp_state_initializer <output.json>\n";
    return 2;
  }
  cfd_ancf::Model model;
  model.length_m = 50.0;
  model.diameter_m = 1.0;
  model.inner_diameter_m = 0.9;
  model.elements = 16;
  model.slices = 3;
  model.slice_positions_m = {8.333333333333334, 25.0, 41.66666666666667};
  model.top_tension_N = 2179104.0029808935;
  model.youngs_modulus_Pa = 3227125779.2218256;
  model.material_density = 26315.789473684214;
  model.fluid_density = 1000.0;
  model.gravity = 9.81;
  model.dt_s = 0.00125;
  model.beta = 0.25;
  model.gamma = 0.5;
  model.max_newton = 40;
  model.newton_tolerance = 1.0e-8;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  try {
    cfd_ancf::validate_model(model);
    auto state = cfd_ancf::make_reference_state(model);
    const auto base_load = cfd_ancf::static_base_load(model);
    const auto fixed = std::vector<std::size_t>{0u, 1u, 2u, 6u * model.elements, 6u * model.elements + 1u};
    constexpr std::size_t LOAD_STEPS = 40;
    std::size_t total_iterations = 0;
    cfd_ancf::StepDiagnostics static_diagnostics;
    try {
      static_diagnostics = cfd_ancf::static_equilibrium(state, model, base_load, LOAD_STEPS, 0.8);
      total_iterations = static_diagnostics.iterations;
    } catch (const std::exception& error) {
      std::cerr << "static equilibrium exception: " << error.what() << '\n';
      return 7;
    }
    std::vector<double> internal;
    cfd_ancf::Matrix tangent;
    cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
    double residual = 0.0;
    std::size_t residual_index = 0;
    for (std::size_t i = 0; i < model.ndof(); ++i) {
      if (std::find(fixed.begin(), fixed.end(), i) == fixed.end())
        if (std::abs(internal[i] - base_load[i]) > residual) {
          residual = std::abs(internal[i] - base_load[i]);
          residual_index = i;
        }
    }
    if (!cfd_ancf::finite(state) || state.q.size() != model.ndof() || !finite_matrix(state.mass) ||
        !std::isfinite(residual)) {
      std::cerr << "initializer produced invalid state\n";
      return 3;
    }
    std::vector<unsigned char> state_bytes;
    state_bytes.reserve((state.q.size() * 3 + state.mass.data.size()) * sizeof(double));
    for (const auto* values : {&state.q, &state.qdot, &state.qddot, &state.base_load})
      for (double value : *values) append_bytes(state_bytes, value);
    for (double value : state.mass.data) append_bytes(state_bytes, value);
    std::array<unsigned char, 32> digest{};
    cfd_ancf::wire::sha256_bytes(state_bytes, digest);
    std::ofstream out(argv[1], std::ios::binary | std::ios::trunc);
    if (!out) return 4;
    out << "{\"architecture\":\"win64\",\"beta\":0.25,\"case_local_bridge_step\":0,"
           "\"equilibrated\":" << (residual <= model.newton_tolerance * (std::max)(1.0, std::abs(model.top_tension_N)) ? "true" : "false") << ",\"finite_value_audit\":true,\"global_step\":0,"
           "\"integer_tick\":0,\"mass_matrix_cols\":" << state.mass.cols << ",\"mass_matrix_rows\":"
        << state.mass.rows << ",\"mass_matrix\":";
    write_array(out, state.mass.data);
    out << ",\"q\":";
    write_array(out, state.q);
    out << ",\"qdot\":";
    write_array(out, state.qdot);
    out << ",\"qddot\":";
    write_array(out, state.qddot);
    out << ",\"base_load\":";
    write_array(out, state.base_load);
    out << ",\"load_steps\":" << LOAD_STEPS << ",\"static_iterations\":" << total_iterations
        << ",\"last_newton_residual\":" << std::setprecision(17) << static_diagnostics.residual
        << ",\"static_residual_inf\":" << std::setprecision(17) << residual
        << ",\"static_residual_index\":" << residual_index
        << ",\"static_internal_at_residual_index\":" << internal[residual_index]
        << ",\"static_base_at_residual_index\":" << base_load[residual_index]
        << ",\"release\":\"cpp_kernel_v1\",\"schema_version\":\"ancf-t0-cpp-v2\","
           "\"state_hash_sha256\":\"" << hex(digest) << "\",\"state_kind\":\"cpp_reference_state\","
           "\"time_s\":0.0,\"worker\":\"cfd_ancf_cpp_state_initializer\"}\n";
    if (!out) return 5;
    std::cout << "cpp_initializer=pass state_hash_sha256=" << hex(digest)
              << " ndof=" << model.ndof() << " equilibrated="
              << (residual <= model.newton_tolerance * (std::max)(1.0, std::abs(model.top_tension_N)) ? "true" : "false")
              << " residual=" << residual << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "initializer exception: " << error.what() << '\n';
    return 6;
  }
}
