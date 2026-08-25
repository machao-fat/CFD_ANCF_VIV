#include "ancf_kernel.hpp"

#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  std::ifstream input(argv[1]);
  std::ofstream output(argv[2], std::ios::trunc);
  if (!input || !output) return 3;
  cfd_ancf::Model model;
  int elements = 0, slices = 0;
  input >> model.length_m >> model.diameter_m >> model.inner_diameter_m >> elements >> slices
        >> model.youngs_modulus_Pa >> model.material_density >> model.fluid_density >> model.gravity
        >> model.beta >> model.gamma >> model.newton_tolerance >> model.gauss_order
        >> model.max_newton >> model.dt_s;
  model.elements = static_cast<std::size_t>(elements);
  model.slices = static_cast<std::size_t>(slices);
  model.slice_positions_m.resize(model.slices);
  for (double& value : model.slice_positions_m) input >> value;
  const std::size_t n = model.ndof();
  cfd_ancf::State state;
  state.q.resize(n); state.qdot.resize(n); state.qddot.resize(n); state.base_load.resize(n);
  for (double& value : state.q) input >> value;
  for (double& value : state.qdot) input >> value;
  for (double& value : state.qddot) input >> value;
  for (double& value : state.base_load) input >> value;
  state.mass = cfd_ancf::Matrix(n, n);
  for (double& value : state.mass.data) input >> value;
  state.damping = cfd_ancf::Matrix(n, n);
  std::vector<double> slice_force(3 * model.slices);
  for (double& value : slice_force) input >> value;
  if (!input) return 4;
  state.time_s = 2.2075;
  state.step = 559;
  std::vector<cfd_ancf::NewtonIterationTrace> trace;
  try { cfd_ancf::advance(state, model, slice_force, &trace); }
  catch (const std::exception& error) { output << "error " << error.what() << '\n'; return 5; }
  output << std::setprecision(17);
  auto write_vector = [&](const char* name, const std::vector<double>& values) {
    output << name << ' ' << values.size();
    for (double value : values) output << ' ' << value;
    output << '\n';
  };
  output << "iterations " << trace.size() << '\n';
  for (const auto& item : trace) {
    output << "iter " << item.iteration << ' ' << (item.converged ? 1 : 0) << ' '
           << item.residual_norm << '\n';
    write_vector("q", item.q);
    write_vector("qdot", item.qdot);
    write_vector("qddot", item.qddot);
    write_vector("internal", item.internal_force);
    write_vector("residual", item.residual);
    write_vector("increment", item.increment);
  }
  return output ? 0 : 6;
}
