#include "physics_ownership.hpp"

#include <cmath>
#include <array>
#include <iomanip>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

using cfd_ancf::Matrix;
using cfd_ancf::Model;
using cfd_ancf::physics_ownership::ForceRepresentation;

namespace {
double norm_inf(const std::vector<double>& values) {
  double result = 0.0;
  for (double value : values) result = std::max(result, std::abs(value));
  return result;
}

double dot(const std::vector<double>& lhs, const std::vector<double>& rhs) {
  if (lhs.size() != rhs.size()) throw std::runtime_error("dot dimensions");
  double result = 0.0;
  for (std::size_t i = 0; i < lhs.size(); ++i) result += lhs[i] * rhs[i];
  return result;
}

double matrix_asymmetry(const Matrix& matrix) {
  double result = 0.0;
  for (std::size_t i = 0; i < matrix.rows; ++i)
    for (std::size_t j = 0; j < matrix.cols; ++j)
      result = std::max(result, std::abs(matrix(i, j) - matrix(j, i)));
  return result;
}

std::vector<double> difference(const std::vector<double>& lhs, const std::vector<double>& rhs) {
  if (lhs.size() != rhs.size()) throw std::runtime_error("difference dimensions");
  std::vector<double> result(lhs.size());
  for (std::size_t i = 0; i < lhs.size(); ++i) result[i] = lhs[i] - rhs[i];
  return result;
}

std::vector<double> mat_vec(const Matrix& matrix, const std::vector<double>& vector) {
  std::vector<double> result(matrix.rows, 0.0);
  for (std::size_t i = 0; i < matrix.rows; ++i)
    for (std::size_t j = 0; j < matrix.cols; ++j) result[i] += matrix(i, j) * vector[j];
  return result;
}

bool near(double value, double expected, double tolerance) {
  return std::abs(value - expected) <= tolerance * std::max(1.0, std::abs(expected));
}

std::pair<std::vector<double>, std::vector<double>> reference_gauss(std::size_t order) {
  if (order == 3) {
    return {{-std::sqrt(3.0 / 5.0), 0.0, std::sqrt(3.0 / 5.0)},
            {5.0 / 9.0, 8.0 / 9.0, 5.0 / 9.0}};
  }
  if (order == 5) {
    const double a = std::sqrt(5.0 + 2.0 * std::sqrt(10.0 / 7.0)) / 3.0;
    const double b = std::sqrt(5.0 - 2.0 * std::sqrt(10.0 / 7.0)) / 3.0;
    return {{-a, -b, 0.0, b, a},
            {(322.0 - 13.0 * std::sqrt(70.0)) / 900.0,
             (322.0 + 13.0 * std::sqrt(70.0)) / 900.0,
             128.0 / 225.0,
             (322.0 + 13.0 * std::sqrt(70.0)) / 900.0,
             (322.0 - 13.0 * std::sqrt(70.0)) / 900.0}};
  }
  throw std::invalid_argument("reference Gauss order");
}

std::array<double, 4> reference_shape(double x, double length) {
  const double xi = x / length;
  return {1.0 - 3.0 * xi * xi + 2.0 * xi * xi * xi,
          length * (xi - 2.0 * xi * xi + xi * xi * xi),
          3.0 * xi * xi - 2.0 * xi * xi * xi,
          length * (-xi * xi + xi * xi * xi)};
}

Matrix independently_integrated_mass(const Model& value, std::size_t order) {
  const auto [points, weights] = reference_gauss(order);
  Matrix result(value.ndof(), value.ndof());
  const double element_length = value.length_m / static_cast<double>(value.elements);
  const double rho_area = value.material_density * value.area();
  for (std::size_t element = 0; element < value.elements; ++element) {
    for (std::size_t k = 0; k < points.size(); ++k) {
      const double x = 0.5 * (points[k] + 1.0) * element_length;
      const auto shape = reference_shape(x, element_length);
      const double weight = weights[k] * element_length / 2.0 * rho_area;
      for (int row_block = 0; row_block < 4; ++row_block) {
        for (int col_block = 0; col_block < 4; ++col_block) {
          const double value_block = weight * shape[static_cast<std::size_t>(row_block)] *
                                     shape[static_cast<std::size_t>(col_block)];
          for (int component = 0; component < 3; ++component) {
            const std::size_t row = 6 * element + 3 * static_cast<std::size_t>(row_block) +
                                    static_cast<std::size_t>(component);
            const std::size_t col = 6 * element + 3 * static_cast<std::size_t>(col_block) +
                                    static_cast<std::size_t>(component);
            result(row, col) += value_block;
          }
        }
      }
    }
  }
  return result;
}

Model model() {
  Model value;
  value.length_m = 10.0;
  value.diameter_m = 1.0;
  value.inner_diameter_m = 0.9;
  value.elements = 2;
  value.slices = 3;
  value.slice_positions_m = {0.0, 5.0, 10.0};
  value.top_tension_N = 1.0e6;
  value.youngs_modulus_Pa = 2.07e11;
  value.material_density = 7850.0;
  value.fluid_density = 1025.0;
  value.gravity = 9.81;
  value.gauss_order = 5;
  value.max_newton = 50;
  return value;
}

}  // namespace

int main() {
  try {
    const Model value = model();
    const auto loads = cfd_ancf::physics_ownership::assemble_base_load(value);
    const double area = value.area();
    const double displaced = value.displaced_area();
    const double expected_gravity = -value.material_density * area * value.gravity * value.length_m;
    const double expected_buoyancy = value.fluid_density * displaced * value.gravity * value.length_m;
    double gravity_sum = 0.0, buoyancy_sum = 0.0;
    for (std::size_t i = 2; i < loads.body_gravity.size(); i += 6) gravity_sum += loads.body_gravity[i];
    for (std::size_t i = 2; i < loads.body_buoyancy.size(); i += 6) buoyancy_sum += loads.body_buoyancy[i];
    const bool load_balance = near(gravity_sum, expected_gravity, 1e-12) &&
                              near(buoyancy_sum, expected_buoyancy, 1e-12) &&
                              near(loads.top_tension[6 * value.elements + 2], value.top_tension_N, 1e-12);

    const std::vector<double> line_force(9, 2.0);
    const std::vector<double> weights = {1.0, 2.0, 3.0};
    const auto integrated = cfd_ancf::physics_ownership::assemble_cfd_load(
        value, {2.0, 2.0, 2.0, 4.0, 4.0, 4.0, 6.0, 6.0, 6.0}, ForceRepresentation::integrated_N);
    const auto line = cfd_ancf::physics_ownership::assemble_cfd_load(
        value, line_force, ForceRepresentation::line_Npm, weights);
    const auto expected_integrated = cfd_ancf::physics_ownership::assemble_cfd_load(
        value, {2.0, 2.0, 2.0, 4.0, 4.0, 4.0, 6.0, 6.0, 6.0},
        ForceRepresentation::integrated_N);
    const bool representation = near(cfd_ancf::physics_ownership::max_abs(
        difference(integrated.generalized_force, expected_integrated.generalized_force)), 0.0, 1e-14) &&
                                line.integrated_slice_force == std::vector<double>{2.0, 2.0, 2.0,
                                                                                     4.0, 4.0, 4.0,
                                                                                     6.0, 6.0, 6.0};

    auto state = cfd_ancf::make_reference_state(value);
    std::vector<double> force;
    Matrix tangent;
    cfd_ancf::internal_force_tangent(state.q, value, force, tangent);
    std::vector<double> direction(state.q.size(), 0.0);
    std::mt19937 generator(7);
    std::uniform_real_distribution<double> distribution(-1.0, 1.0);
    for (double& component : direction) component = distribution(generator);
    const double epsilon = 1.0e-6;
    auto plus = state.q, minus = state.q;
    for (std::size_t i = 0; i < plus.size(); ++i) {
      plus[i] += epsilon * direction[i];
      minus[i] -= epsilon * direction[i];
    }
    std::vector<double> force_plus, force_minus;
    Matrix tangent_plus, tangent_minus;
    cfd_ancf::internal_force_tangent(plus, value, force_plus, tangent_plus);
    cfd_ancf::internal_force_tangent(minus, value, force_minus, tangent_minus);
    const auto finite_difference = [&]() {
      std::vector<double> result(force.size());
      for (std::size_t i = 0; i < result.size(); ++i) result[i] = (force_plus[i] - force_minus[i]) / (2.0 * epsilon);
      return result;
    }();
    const double tangent_error = norm_inf(difference(mat_vec(tangent, direction), finite_difference));
    const double tangent_scale = std::max(1.0, norm_inf(finite_difference));
    const double tangent_relative_error = tangent_error / tangent_scale;
    const bool tangent_fd = tangent_relative_error < 5.0e-6;

    auto rigid = state.q;
    for (std::size_t node = 0; node <= value.elements; ++node) {
      rigid[6 * node] += 0.3;
      rigid[6 * node + 1] -= 0.2;
    }
    std::vector<double> rigid_force;
    Matrix rigid_tangent;
    cfd_ancf::internal_force_tangent(rigid, value, rigid_force, rigid_tangent);
    const double rigid_error = norm_inf(rigid_force);
    const double rigid_scale = std::max(1.0, value.EA());
    const double rigid_relative_error = rigid_error / rigid_scale;
    const bool rigid_translation = rigid_relative_error < 1.0e-12;

    auto rotated = state.q;
    for (std::size_t node = 0; node <= value.elements; ++node) {
      const std::size_t base = 6 * node;
      const double position_y = rotated[base + 1];
      const double position_z = rotated[base + 2];
      const double derivative_y = rotated[base + 4];
      const double derivative_z = rotated[base + 5];
      rotated[base + 1] = -position_z;
      rotated[base + 2] = position_y;
      rotated[base + 4] = -derivative_z;
      rotated[base + 5] = derivative_y;
    }
    std::vector<double> rotated_force;
    Matrix rotated_tangent;
    cfd_ancf::internal_force_tangent(rotated, value, rotated_force, rotated_tangent);
    const double rigid_rotation_error = norm_inf(rotated_force);
    const bool rigid_rotation = rigid_rotation_error / rigid_scale < 1.0e-12;

    const bool tangent_symmetric = matrix_asymmetry(tangent) / std::max(1.0, value.EA()) < 1.0e-14;
    const auto mapping = cfd_ancf::mapping_H3(value);
    std::vector<double> virtual_displacement(mapping.cols, 0.0);
    for (std::size_t i = 0; i < virtual_displacement.size(); ++i)
      virtual_displacement[i] = distribution(generator);
    const std::vector<double> slice_work = mat_vec(mapping, virtual_displacement);
    const std::vector<double> slice_values{1.2, -0.5, 0.7, -0.2, 0.8, -1.1,
                                           0.4, 0.3, -0.9};
    const auto mapped = cfd_ancf::external_force(value, slice_values);
    const bool virtual_work = near(dot(mapped, virtual_displacement),
                                   dot(slice_values, slice_work), 1.0e-12);

    std::vector<double> zero_internal;
    Matrix zero_tangent;
    cfd_ancf::internal_force_tangent(state.q, value, zero_internal, zero_tangent);
    const bool zero_load_limit = norm_inf(zero_internal) / std::max(1.0, value.EA()) < 1.0e-14;

    const double stretch_factor = 1.01;
    auto stretched = state.q;
    for (double& component : stretched) component *= stretch_factor;
    std::vector<double> stretched_force;
    Matrix stretched_tangent;
    cfd_ancf::internal_force_tangent(stretched, value, stretched_force, stretched_tangent);
    const double stretch_strain = 0.5 * (stretch_factor * stretch_factor - 1.0);
    const double expected_axial_work = value.EA() * stretch_strain * stretch_factor * value.length_m;
    const double axial_work_error = std::abs(dot(stretched_force, state.q) - expected_axial_work);
    const double axial_work_relative_error = axial_work_error / std::max(1.0, std::abs(expected_axial_work));
    const bool axial_patch = axial_work_relative_error < 1.0e-12;

    Model gravity_only = value;
    gravity_only.include_buoyancy = false;
    gravity_only.top_tension_N = 0.0;
    Model buoyancy_only = value;
    buoyancy_only.include_gravity = false;
    buoyancy_only.top_tension_N = 0.0;
    Model top_only = value;
    top_only.include_gravity = false;
    top_only.include_buoyancy = false;
    const auto gravity_load = cfd_ancf::physics_ownership::assemble_base_load(gravity_only);
    const auto buoyancy_load = cfd_ancf::physics_ownership::assemble_base_load(buoyancy_only);
    const auto top_load = cfd_ancf::physics_ownership::assemble_base_load(top_only);
    const bool component_limits = norm_inf(gravity_load.body_buoyancy) == 0.0 &&
                                  norm_inf(gravity_load.top_tension) == 0.0 &&
                                  norm_inf(buoyancy_load.body_gravity) == 0.0 &&
                                  norm_inf(buoyancy_load.top_tension) == 0.0 &&
                                  norm_inf(top_load.body_gravity) == 0.0 &&
                                  norm_inf(top_load.body_buoyancy) == 0.0 &&
                                  near(top_load.top_tension[6 * value.elements + 2], value.top_tension_N, 1e-12);

    Model unloaded = value;
    unloaded.include_gravity = false;
    unloaded.include_buoyancy = false;
    unloaded.top_tension_N = 0.0;
    unloaded.newton_tolerance = 1.0e-4;
    auto continuous = cfd_ancf::make_reference_state(unloaded);
    auto before_restart = cfd_ancf::make_reference_state(unloaded);
    const std::vector<double> no_force(3 * unloaded.slices, 0.0);
    cfd_ancf::advance(continuous, unloaded, no_force);
    cfd_ancf::advance(continuous, unloaded, no_force);
    cfd_ancf::advance(before_restart, unloaded, no_force);
    auto after_restart = before_restart;
    cfd_ancf::advance(after_restart, unloaded, no_force);
    const bool restart_equivalent = continuous.step == 2 && after_restart.step == 2 &&
                                    norm_inf(difference(continuous.q, after_restart.q)) < 1.0e-12 &&
                                    norm_inf(difference(continuous.qdot, after_restart.qdot)) < 1.0e-12 &&
                                    norm_inf(difference(continuous.qddot, after_restart.qddot)) < 1.0e-12;

    auto loaded_state = cfd_ancf::make_reference_state(unloaded);
    std::vector<double> loaded_force(3 * unloaded.slices, 0.0);
    loaded_force[3] = 1.0e3;
    const auto q_before = loaded_state.q;
    const auto qdot_before = loaded_state.qdot;
    const auto qddot_before = loaded_state.qddot;
    const auto loaded_diag = cfd_ancf::advance(loaded_state, unloaded, loaded_force);
    std::vector<double> qpred(q_before.size()), qdpred(q_before.size());
    for (std::size_t i = 0; i < qpred.size(); ++i) {
      qpred[i] = q_before[i] + unloaded.dt_s * qdot_before[i] +
                 unloaded.dt_s * unloaded.dt_s * (0.5 - unloaded.beta) * qddot_before[i];
      qdpred[i] = qdot_before[i] + unloaded.dt_s * (1.0 - unloaded.gamma) * qddot_before[i];
    }
    double newmark_error = 0.0;
    double newmark_scale = 1.0;
    for (std::size_t i = 0; i < qpred.size(); ++i) {
      const double expected_q = qpred[i] + unloaded.beta * unloaded.dt_s * unloaded.dt_s * loaded_state.qddot[i];
      const double expected_qdot = qdpred[i] + unloaded.gamma * unloaded.dt_s * loaded_state.qddot[i];
      newmark_error = std::max(newmark_error, std::abs(loaded_state.q[i] - expected_q));
      newmark_error = std::max(newmark_error, std::abs(loaded_state.qdot[i] - expected_qdot));
      newmark_scale = std::max(newmark_scale, std::abs(expected_q));
      newmark_scale = std::max(newmark_scale, std::abs(expected_qdot));
    }
    const double newmark_relative_error = newmark_error / newmark_scale;
    const bool newmark_consistent = loaded_diag.converged && loaded_diag.residual <= 1.0e-4 &&
                                    newmark_relative_error < 1.0e-12;

    const auto run_loaded = [](Model configured, std::size_t steps) {
      auto result = cfd_ancf::make_reference_state(configured);
      std::vector<double> load(3 * configured.slices, 0.0);
      if (configured.slices > 1) load[3] = 1.0e3;
      for (std::size_t step = 0; step < steps; ++step)
        cfd_ancf::advance(result, configured, load);
      return result;
    };
    Model coarse_time = unloaded;
    coarse_time.dt_s = 1.25e-3;
    auto coarse_result = run_loaded(coarse_time, 2);
    Model fine_time = unloaded;
    fine_time.dt_s = 0.625e-3;
    auto fine_result = run_loaded(fine_time, 4);
    const double time_step_error = norm_inf(difference(coarse_result.q, fine_result.q));
    const double time_step_scale = std::max(1.0, norm_inf(fine_result.q));
    const double time_step_relative_error = time_step_error / time_step_scale;
    const bool time_step_convergence = std::isfinite(time_step_relative_error) && time_step_relative_error < 1.0;

    Model coarse_grid = unloaded;
    coarse_grid.elements = 2;
    coarse_grid.slice_positions_m = {0.0, 5.0, 10.0};
    Model fine_grid = unloaded;
    fine_grid.elements = 4;
    fine_grid.slice_positions_m = {0.0, 5.0, 10.0};
    auto coarse_grid_result = run_loaded(coarse_grid, 1);
    auto fine_grid_result = run_loaded(fine_grid, 1);
    const double grid_midpoint_error = std::abs(coarse_grid_result.q[6] - fine_grid_result.q[12]);
    const double grid_midpoint_scale = std::max(1.0, std::abs(fine_grid_result.q[12]));
    const double grid_relative_error = grid_midpoint_error / grid_midpoint_scale;
    const bool grid_convergence = std::isfinite(grid_relative_error) && grid_relative_error < 1.0;

    bool invalid_representation_rejected = false;
    try {
      (void)cfd_ancf::physics_ownership::assemble_cfd_load(
          value, std::vector<double>(8, 0.0), ForceRepresentation::integrated_N);
    } catch (const std::invalid_argument&) {
      invalid_representation_rejected = true;
    }
    bool invalid_line_weight_rejected = false;
    try {
      (void)cfd_ancf::physics_ownership::assemble_cfd_load(
          value, line_force, ForceRepresentation::line_Npm, {1.0, 0.0, 1.0});
    } catch (const std::invalid_argument&) {
      invalid_line_weight_rejected = true;
    }

    const auto reference = cfd_ancf::make_reference_state(value);
    // The frozen MATLAB contract applies top tension in the global +z
    // translational DOF.  It is not reoriented to a bent current tangent.
    auto bent_state = reference.q;
    for (std::size_t node = 1; node <= value.elements; ++node) {
      bent_state[6 * node] += 0.05 * static_cast<double>(node);
      bent_state[6 * node + 1] -= 0.03 * static_cast<double>(node);
    }
    const std::size_t top_dof = 6 * value.elements;
    bent_state[top_dof] += 0.2;
    bent_state[top_dof + 1] -= 0.1;
    const bool bent_state_is_nontrivial =
        norm_inf(difference(bent_state, reference.q)) > 0.0;
    const auto bent_contract_load = cfd_ancf::physics_ownership::assemble_base_load(value);
    bool top_tension_global_z_contract = true;
    for (std::size_t index = 0; index < bent_contract_load.top_tension.size(); ++index) {
      const double expected = index == top_dof + 2 ? value.top_tension_N : 0.0;
      if (bent_contract_load.top_tension[index] != expected) top_tension_global_z_contract = false;
    }
    const auto bent_repeat_load = cfd_ancf::physics_ownership::assemble_base_load(value);
    const bool bent_state_does_not_rotate_top_tension =
        bent_state_is_nontrivial &&
        norm_inf(difference(bent_contract_load.top_tension, bent_repeat_load.top_tension)) == 0.0 &&
        bent_contract_load.top_tension[top_dof] == 0.0 &&
        bent_contract_load.top_tension[top_dof + 1] == 0.0 &&
        bent_contract_load.top_tension[top_dof + 2] == value.top_tension_N;
    const auto owned_mass = cfd_ancf::physics_ownership::assemble_mass_matrix(value);
    const double mass_assembly_error = norm_inf(difference(reference.mass.data, owned_mass.data));
    const double mass_assembly_scale = std::max(1.0, norm_inf(reference.mass.data));
    const bool mass_assembly_matches_kernel = mass_assembly_error <= 1.0e-14 * mass_assembly_scale;
    Model order3 = value;
    order3.gauss_order = 3;
    Model order5 = value;
    order5.gauss_order = 5;
    const auto mass3 = cfd_ancf::physics_ownership::assemble_mass_matrix(order3);
    const auto mass5 = cfd_ancf::physics_ownership::assemble_mass_matrix(order5);
    const auto kernel_mass3 = cfd_ancf::make_reference_state(order3).mass;
    const auto kernel_mass5 = cfd_ancf::make_reference_state(order5).mass;
    // MATLAB ancf_mass_matrix.m always uses five-point quadrature; the
    // model gauss_order applies to nonlinear force/tangent integration only.
    const auto expected_mass3 = independently_integrated_mass(order3, 5);
    const auto expected_mass5 = independently_integrated_mass(order5, 5);
    const double mass_order3_error = norm_inf(difference(mass3.data, expected_mass3.data));
    const double mass_order5_error = norm_inf(difference(mass5.data, expected_mass5.data));
    const double kernel_mass_order3_error =
        norm_inf(difference(kernel_mass3.data, expected_mass3.data));
    const double kernel_mass_order5_error =
        norm_inf(difference(kernel_mass5.data, expected_mass5.data));
    const double mass_order_scale = std::max(1.0, norm_inf(expected_mass5.data));
    const double mass_order_difference = norm_inf(difference(mass3.data, mass5.data));
    const bool mass_order_contract =
        mass_order3_error <= 1.0e-14 * mass_order_scale &&
        mass_order5_error <= 1.0e-14 * mass_order_scale &&
        kernel_mass_order3_error <= 1.0e-14 * mass_order_scale &&
        kernel_mass_order5_error <= 1.0e-14 * mass_order_scale &&
        mass_order_difference <= 1.0e-14 * mass_order_scale;
    bool invalid_gauss_rejected = false;
    try {
      Model invalid = value;
      invalid.gauss_order = 4;
      (void)cfd_ancf::physics_ownership::assemble_mass_matrix(invalid);
    } catch (const std::invalid_argument&) {
      invalid_gauss_rejected = true;
    }
    bool mass_symmetric = true;
    bool mass_positive = true;
    for (std::size_t i = 0; i < reference.mass.rows; ++i) {
      for (std::size_t j = 0; j < reference.mass.cols; ++j) {
        if (std::abs(reference.mass(i, j) - reference.mass(j, i)) > 1e-12) mass_symmetric = false;
      }
    }
    for (int sample = 0; sample < 10; ++sample) {
      std::vector<double> vector(reference.mass.rows);
      for (double& component : vector) component = distribution(generator);
      const auto image = mat_vec(reference.mass, vector);
      double quadratic = 0.0;
      for (std::size_t i = 0; i < vector.size(); ++i) quadratic += vector[i] * image[i];
      if (!(quadratic > 0.0)) mass_positive = false;
    }

    const bool pass = load_balance && representation && tangent_fd && rigid_translation &&
                      rigid_rotation && tangent_symmetric && virtual_work && restart_equivalent &&
                      zero_load_limit && axial_patch && component_limits && newmark_consistent &&
                      time_step_convergence && grid_convergence &&
                      invalid_representation_rejected && invalid_line_weight_rejected &&
                      mass_symmetric && mass_positive && mass_assembly_matches_kernel &&
                      mass_order_contract && invalid_gauss_rejected &&
                      top_tension_global_z_contract && bent_state_does_not_rotate_top_tension;
    const auto loads_hash = [](const std::vector<double>& values) {
      return cfd_ancf::physics_ownership::sha256_vector(values);
    };
    const auto mass_hash = loads_hash(owned_mass.data);
    std::cout << std::setprecision(17)
              << "{\"status\":\"" << (pass ? "pass" : "do_not_pass")
              << "\",\"load_balance\":" << (load_balance ? "true" : "false")
              << ",\"force_representation\":" << (representation ? "true" : "false")
              << ",\"tangent_finite_difference\":" << (tangent_fd ? "true" : "false")
              << ",\"rigid_translation\":" << (rigid_translation ? "true" : "false")
              << ",\"mass_symmetric\":" << (mass_symmetric ? "true" : "false")
              << ",\"mass_positive_samples\":" << (mass_positive ? "true" : "false")
              << ",\"mass_assembly_matches_kernel\":"
              << (mass_assembly_matches_kernel ? "true" : "false")
              << ",\"mass_order_contract\":" << (mass_order_contract ? "true" : "false")
              << ",\"invalid_gauss_rejected\":"
              << (invalid_gauss_rejected ? "true" : "false")
              << ",\"mass_order3_error\":" << mass_order3_error
              << ",\"mass_order5_error\":" << mass_order5_error
              << ",\"kernel_mass_order3_error\":" << kernel_mass_order3_error
              << ",\"kernel_mass_order5_error\":" << kernel_mass_order5_error
              << ",\"mass_order_difference\":" << mass_order_difference
              << ",\"mass_order_scale\":" << mass_order_scale
              << ",\"top_tension_global_z_contract\":"
              << (top_tension_global_z_contract ? "true" : "false")
              << ",\"bent_state_does_not_rotate_top_tension\":"
              << (bent_state_does_not_rotate_top_tension ? "true" : "false")
              << ",\"mass_assembly_error\":" << mass_assembly_error
              << ",\"mass_assembly_scale\":" << mass_assembly_scale
              << ",\"tangent_symmetric\":" << (tangent_symmetric ? "true" : "false")
              << ",\"rigid_rotation\":" << (rigid_rotation ? "true" : "false")
              << ",\"virtual_work\":" << (virtual_work ? "true" : "false")
              << ",\"restart_equivalent\":" << (restart_equivalent ? "true" : "false")
              << ",\"zero_load_limit\":" << (zero_load_limit ? "true" : "false")
              << ",\"axial_patch\":" << (axial_patch ? "true" : "false")
              << ",\"component_limits\":" << (component_limits ? "true" : "false")
              << ",\"newmark_consistent\":" << (newmark_consistent ? "true" : "false")
              << ",\"time_step_convergence\":" << (time_step_convergence ? "true" : "false")
              << ",\"grid_convergence\":" << (grid_convergence ? "true" : "false")
              << ",\"invalid_representation_rejected\":"
              << (invalid_representation_rejected ? "true" : "false")
              << ",\"invalid_line_weight_rejected\":"
              << (invalid_line_weight_rejected ? "true" : "false")
              << ",\"gravity_sum\":" << gravity_sum
              << ",\"buoyancy_sum\":" << buoyancy_sum
              << ",\"tangent_error\":" << tangent_error
              << ",\"tangent_scale\":" << tangent_scale
              << ",\"tangent_relative_error\":" << tangent_relative_error
              << ",\"rigid_error\":" << rigid_error
              << ",\"rigid_scale\":" << rigid_scale
              << ",\"axial_work_relative_error\":" << axial_work_relative_error
              << ",\"newmark_relative_error\":" << newmark_relative_error
              << ",\"time_step_relative_error\":" << time_step_relative_error
              << ",\"grid_relative_error\":" << grid_relative_error
              << ",\"rigid_relative_error\":" << rigid_relative_error
              << ",\"component_sha256\":{\"body_gravity\":\""
              << loads_hash(loads.body_gravity) << "\",\"body_buoyancy\":\""
              << loads_hash(loads.body_buoyancy) << "\",\"top_tension\":\""
              << loads_hash(loads.top_tension) << "\",\"base\":\""
              << loads_hash(loads.base) << "\",\"mass\":\""
              << mass_hash << "\"}}\n";
    return pass ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << "physics ownership selftest failed: " << error.what() << '\n';
    return 2;
  }
}
