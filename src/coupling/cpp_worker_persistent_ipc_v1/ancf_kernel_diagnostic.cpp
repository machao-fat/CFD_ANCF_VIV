#include "ancf_kernel.hpp"

#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

// Diagnostic-only executable. It consumes a whitespace fixture produced by
// the Python audit and writes the same intermediate vectors as the MATLAB
// diagnostic. It does not start MATLAB, OpenFOAM, WSL, or CFD.
int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: diagnostic <fixture.txt> <output.txt>\n";
    return 2;
  }
  std::ifstream input(argv[1]);
  std::ofstream output(argv[2], std::ios::trunc);
  if (!input || !output) return 3;

  cfd_ancf::Model model;
  int elements = 0;
  int slices = 0;
  input >> model.length_m >> model.diameter_m >> model.inner_diameter_m
        >> elements >> slices >> model.youngs_modulus_Pa
        >> model.material_density >> model.fluid_density >> model.gravity
        >> model.beta >> model.gamma >> model.newton_tolerance
        >> model.gauss_order >> model.max_newton >> model.dt_s;
  model.elements = static_cast<std::size_t>(elements);
  model.slices = static_cast<std::size_t>(slices);
  model.slice_positions_m.resize(model.slices);
  for (double& position : model.slice_positions_m) input >> position;
  const std::size_t n = model.ndof();
  cfd_ancf::State state;
  state.q.resize(n); state.qdot.resize(n); state.qddot.resize(n);
  state.base_load.resize(n);
  for (double& value : state.q) input >> value;
  for (double& value : state.qdot) input >> value;
  for (double& value : state.qddot) input >> value;
  for (double& value : state.base_load) input >> value;
  state.mass = cfd_ancf::Matrix(n, n);
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = 0; j < n; ++j) input >> state.mass(i, j);
  state.damping = cfd_ancf::Matrix(n, n);
  std::vector<double> slice_force(3 * model.slices);
  for (double& value : slice_force) input >> value;
  if (!input) return 4;

  std::vector<double> internal;
  cfd_ancf::Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  std::vector<double> predictor(n), velocity_predictor(n);
  for (std::size_t i = 0; i < n; ++i) {
    predictor[i] = state.q[i] + model.dt_s * state.qdot[i] +
                   model.dt_s * model.dt_s * (0.5 - model.beta) * state.qddot[i];
    velocity_predictor[i] = state.qdot[i] + model.dt_s * (1.0 - model.gamma) * state.qddot[i];
  }
  auto write_vector = [&](const char* name, const std::vector<double>& values) {
    output << name << ' ' << values.size();
    output << std::setprecision(17);
    for (double value : values) output << ' ' << value;
    output << '\n';
  };
  write_vector("internal_before", internal);
  write_vector("predictor", predictor);
  write_vector("velocity_predictor", velocity_predictor);
  output << "mass " << state.mass.rows << ' ' << state.mass.cols << '\n';
  output << std::setprecision(17);
  for (double value : state.mass.data) output << value << ' ';
  output << '\n';
  output << "tangent " << tangent.rows << ' ' << tangent.cols << '\n';
  for (double value : tangent.data) output << value << ' ';
  output << '\n';
  return 0;
}
