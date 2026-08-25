#include "ancf_kernel.hpp"

#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>

// Diagnostic-only executable. It reads the existing text fixture format and
// emits a lossless, line-oriented trace for offline MATLAB/C++ comparison.
int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: forensic_diagnostic <fixture.txt> <trace.txt>\n";
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
  state.q.resize(n);
  state.qdot.resize(n);
  state.qddot.resize(n);
  state.base_load.resize(n);
  for (double& value : state.q) input >> value;
  for (double& value : state.qdot) input >> value;
  for (double& value : state.qddot) input >> value;
  for (double& value : state.base_load) input >> value;
  state.mass = cfd_ancf::Matrix(n, n);
  for (double& value : state.mass.data) input >> value;
  std::vector<double> slice_force(3 * model.slices);
  for (double& value : slice_force) input >> value;
  if (!input) return 4;
  const auto trace = cfd_ancf::internal_force_forensic(state.q, model);
  output << std::setprecision(17);
  output << "meta " << model.elements << ' ' << model.gauss_order << ' '
         << trace.points.size() << ' ' << n << '\n';
  for (const auto& point : trace.points) {
    output << "point " << point.element << ' ' << point.gauss_index << ' '
           << point.xi << ' ' << point.x << ' ';
    for (double value : point.a) output << value << ' ';
    for (double value : point.b) output << value << ' ';
    for (double value : point.v) output << value << ' ';
    output << point.a2 << ' ' << point.v2 << ' ' << point.eps << ' ';
    for (double value : point.ga_b) output << value << ' ';
    for (double value : point.gb_b) output << value << ' ';
    for (double value : point.ga) output << value << ' ';
    for (double value : point.gb) output << value << ' ';
    for (double value : point.bga) output << value << ' ';
    for (double value : point.cgb) output << value << ' ';
    for (double value : point.contribution) output << value << ' ';
    output << '\n';
  }
  output << "force " << trace.force.size();
  for (double value : trace.force) output << ' ' << value;
  output << '\n';
  output << "tangent " << trace.tangent.rows << ' ' << trace.tangent.cols;
  for (double value : trace.tangent.data) output << ' ' << value;
  output << '\n';
  return output ? 0 : 5;
}
