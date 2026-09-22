#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr double Pi = 3.141592653589793238462643383279502884;
constexpr std::size_t Elements = 16;
constexpr std::size_t Modes = 6;
constexpr std::size_t LoadSteps = 40;
constexpr double StaticRelaxation = 0.8;
constexpr double FrequencyTolerance = 5.0e-3;
constexpr double StaticResidualTolerance = 1.0e-8;
constexpr double MatrixSymmetryTolerance = 1.0e-12;
constexpr double EigenResidualTolerance = 1.0e-9;
constexpr double MOrthogonalityTolerance = 1.0e-8;

const double ReferenceFrequencies[] = {
    0.19876102675389518,
    0.476181930710043,
    0.8702401692325742,
    1.3985123281821055,
    2.068594917195311,
    2.8842837351244612};

struct EigenSystem {
  std::vector<double> values;
  cfd_ancf::Matrix vectors;
};

double dot(const std::vector<double>& left, const std::vector<double>& right) {
  if (left.size() != right.size()) throw std::invalid_argument("dot dimensions");
  double value = 0.0;
  for (std::size_t i = 0; i < left.size(); ++i) value += left[i] * right[i];
  return value;
}

double norm2(const std::vector<double>& value) { return std::sqrt(dot(value, value)); }

std::vector<double> multiply(const cfd_ancf::Matrix& matrix,
                             const std::vector<double>& vector) {
  if (matrix.cols != vector.size()) throw std::invalid_argument("matrix/vector dimensions");
  std::vector<double> result(matrix.rows, 0.0);
  for (std::size_t row = 0; row < matrix.rows; ++row)
    for (std::size_t col = 0; col < matrix.cols; ++col)
      result[row] += matrix(row, col) * vector[col];
  return result;
}

cfd_ancf::Matrix transpose(const cfd_ancf::Matrix& matrix) {
  cfd_ancf::Matrix result(matrix.cols, matrix.rows);
  for (std::size_t row = 0; row < matrix.rows; ++row)
    for (std::size_t col = 0; col < matrix.cols; ++col)
      result(col, row) = matrix(row, col);
  return result;
}

cfd_ancf::Matrix multiply(const cfd_ancf::Matrix& left,
                           const cfd_ancf::Matrix& right) {
  if (left.cols != right.rows) throw std::invalid_argument("matrix dimensions");
  cfd_ancf::Matrix result(left.rows, right.cols);
  for (std::size_t row = 0; row < left.rows; ++row)
    for (std::size_t mid = 0; mid < left.cols; ++mid)
      for (std::size_t col = 0; col < right.cols; ++col)
        result(row, col) += left(row, mid) * right(mid, col);
  return result;
}

cfd_ancf::Matrix select(const cfd_ancf::Matrix& source,
                        const std::vector<std::size_t>& indices) {
  cfd_ancf::Matrix result(indices.size(), indices.size());
  for (std::size_t row = 0; row < indices.size(); ++row)
    for (std::size_t col = 0; col < indices.size(); ++col)
      result(row, col) = source(indices[row], indices[col]);
  return result;
}

cfd_ancf::Matrix cholesky_lower(const cfd_ancf::Matrix& matrix) {
  if (matrix.rows != matrix.cols) throw std::invalid_argument("mass matrix is not square");
  cfd_ancf::Matrix lower(matrix.rows, matrix.cols);
  for (std::size_t row = 0; row < matrix.rows; ++row) {
    for (std::size_t col = 0; col <= row; ++col) {
      double value = matrix(row, col);
      for (std::size_t k = 0; k < col; ++k) value -= lower(row, k) * lower(col, k);
      if (row == col) {
        if (!std::isfinite(value) || value <= 0.0)
          throw std::runtime_error("mass matrix is not positive definite");
        lower(row, col) = std::sqrt(value);
      } else {
        lower(row, col) = value / lower(col, col);
      }
    }
  }
  return lower;
}

cfd_ancf::Matrix inverse_lower(const cfd_ancf::Matrix& lower) {
  cfd_ancf::Matrix inverse(lower.rows, lower.cols);
  for (std::size_t col = 0; col < lower.cols; ++col) {
    for (std::size_t row = 0; row < lower.rows; ++row) {
      double value = row == col ? 1.0 : 0.0;
      for (std::size_t k = 0; k < row; ++k) value -= lower(row, k) * inverse(k, col);
      inverse(row, col) = value / lower(row, row);
    }
  }
  return inverse;
}

EigenSystem jacobi_symmetric(cfd_ancf::Matrix matrix) {
  if (matrix.rows != matrix.cols) throw std::invalid_argument("eigen matrix is not square");
  const std::size_t n = matrix.rows;
  cfd_ancf::Matrix vectors(n, n);
  for (std::size_t i = 0; i < n; ++i) vectors(i, i) = 1.0;
  double scale = 1.0;
  for (double value : matrix.data) scale = (std::max)(scale, std::abs(value));
  const std::size_t max_iterations = 100u * n * n;
  for (std::size_t iteration = 0; iteration < max_iterations; ++iteration) {
    std::size_t p = 0, q = 1;
    double maximum = 0.0;
    for (std::size_t row = 0; row < n; ++row) {
      for (std::size_t col = row + 1; col < n; ++col) {
        if (std::abs(matrix(row, col)) > maximum) {
          maximum = std::abs(matrix(row, col));
          p = row;
          q = col;
        }
      }
    }
    if (maximum <= 1.0e-12 * scale) {
      std::vector<std::size_t> order(n);
      std::iota(order.begin(), order.end(), 0u);
      std::sort(order.begin(), order.end(), [&matrix](std::size_t left, std::size_t right) {
        return matrix(left, left) < matrix(right, right);
      });
      EigenSystem result;
      result.values.resize(n);
      result.vectors = cfd_ancf::Matrix(n, n);
      for (std::size_t column = 0; column < n; ++column) {
        result.values[column] = matrix(order[column], order[column]);
        for (std::size_t row = 0; row < n; ++row)
          result.vectors(row, column) = vectors(row, order[column]);
      }
      return result;
    }
    const double app = matrix(p, p), aqq = matrix(q, q), apq = matrix(p, q);
    const double angle = 0.5 * std::atan2(2.0 * apq, aqq - app);
    const double cosine = std::cos(angle), sine = std::sin(angle);
    for (std::size_t index = 0; index < n; ++index) {
      if (index == p || index == q) continue;
      const double aip = matrix(index, p), aiq = matrix(index, q);
      matrix(index, p) = matrix(p, index) = cosine * aip - sine * aiq;
      matrix(index, q) = matrix(q, index) = sine * aip + cosine * aiq;
    }
    matrix(p, p) = cosine * cosine * app - 2.0 * sine * cosine * apq + sine * sine * aqq;
    matrix(q, q) = sine * sine * app + 2.0 * sine * cosine * apq + cosine * cosine * aqq;
    matrix(p, q) = matrix(q, p) = 0.0;
    for (std::size_t index = 0; index < n; ++index) {
      const double vip = vectors(index, p), viq = vectors(index, q);
      vectors(index, p) = cosine * vip - sine * viq;
      vectors(index, q) = sine * vip + cosine * viq;
    }
  }
  throw std::runtime_error("Jacobi eigensolver did not converge");
}

std::vector<std::size_t> free_y_dof(const cfd_ancf::Model& model) {
  std::vector<std::size_t> result;
  for (std::size_t node = 0; node <= model.elements; ++node) {
    if (node != 0 && node != model.elements) result.push_back(6u * node + 1u);
    result.push_back(6u * node + 4u);
  }
  return result;
}

cfd_ancf::Model make_model() {
  cfd_ancf::Model model;
  model.length_m = 50.0;
  model.diameter_m = 1.0;
  model.inner_diameter_m = 0.9;
  model.elements = Elements;
  model.slices = 3;
  model.slice_positions_m = {8.333333333333334, 25.0, 41.666666666666664};
  model.top_tension_N = 2179104.0029808935;
  model.youngs_modulus_Pa = 3227125779.2218256;
  model.material_density = 26315.789473684214;
  model.fluid_density = 1000.0;
  model.gravity = 9.81;
  model.include_gravity = true;
  model.include_buoyancy = true;
  model.dt_s = 0.005;
  model.beta = 0.25;
  model.gamma = 0.5;
  model.max_newton = 40;
  model.newton_tolerance = 1.0e-8;
  model.damping_alpha = 0.0;
  model.damping_beta = 0.0;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  cfd_ancf::validate_model(model);
  return model;
}

void write_vector(const std::string& path, const std::vector<double>& values) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write vector evidence");
  out << std::setprecision(17);
  for (double value : values) out << value << '\n';
}

void write_indices(const std::string& path, const std::vector<std::size_t>& values) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write free-DOF evidence");
  for (std::size_t value : values) out << value << '\n';
}

void write_matrix(const std::string& path, const cfd_ancf::Matrix& matrix) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write matrix evidence");
  out << std::setprecision(17);
  for (std::size_t row = 0; row < matrix.rows; ++row) {
    for (std::size_t col = 0; col < matrix.cols; ++col) {
      if (col != 0) out << ' ';
      out << matrix(row, col);
    }
    out << '\n';
  }
}

double symmetry_error(const cfd_ancf::Matrix& matrix) {
  double numerator = 0.0, denominator = 0.0;
  for (std::size_t row = 0; row < matrix.rows; ++row) {
    for (std::size_t col = 0; col < matrix.cols; ++col) {
      numerator += std::pow(matrix(row, col) - matrix(col, row), 2.0);
      denominator += std::pow(matrix(row, col), 2.0);
    }
  }
  return std::sqrt(numerator) / (std::max)(std::sqrt(denominator), 1.0e-300);
}

std::vector<double> extract_column(const cfd_ancf::Matrix& matrix, std::size_t column) {
  std::vector<double> result(matrix.rows);
  for (std::size_t row = 0; row < matrix.rows; ++row) result[row] = matrix(row, column);
  return result;
}

double frobenius(const cfd_ancf::Matrix& matrix) {
  double sum = 0.0;
  for (double value : matrix.data) sum += value * value;
  return std::sqrt(sum);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 10) {
    std::cerr << "usage: modal <stdout-tag> <modes.csv> <reconstruction.csv> <q> <Mfull> <Mff> <Kfull> <Kff> <free>\n";
    return 2;
  }
  try {
    const cfd_ancf::Model model = make_model();
    cfd_ancf::State state = cfd_ancf::make_reference_state(model);
    const std::vector<double> base_load = cfd_ancf::static_base_load(model);
    const cfd_ancf::StepDiagnostics static_diag =
        cfd_ancf::static_equilibrium(state, model, base_load, LoadSteps, StaticRelaxation);
    if (!static_diag.converged) throw std::runtime_error("D_PRESTRESS_EQUILIBRIUM_FAIL");
    if (!cfd_ancf::finite(state)) throw std::runtime_error("D_NONFINITE_RESULT");

    std::vector<std::size_t> fixed = {0u, 1u, 2u, 6u * Elements, 6u * Elements + 1u};
    double max_fixed_error = 0.0;
    const double prescribed[] = {0.0, 0.0, 0.0, 0.0, 0.0};
    for (std::size_t i = 0; i < fixed.size(); ++i)
      max_fixed_error = (std::max)(max_fixed_error, std::abs(state.q[fixed[i]] - prescribed[i]));
    const double normalized_static_residual = static_diag.residual / static_diag.residual_scale;
    if (max_fixed_error > 1.0e-12 || !std::isfinite(normalized_static_residual) ||
        normalized_static_residual > StaticResidualTolerance)
      throw std::runtime_error("D_PRESTRESS_EQUILIBRIUM_FAIL");

    std::vector<double> internal;
    cfd_ancf::Matrix tangent;
    cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
    std::vector<double> reaction(internal.size(), 0.0);
    for (std::size_t i = 0; i < reaction.size(); ++i) reaction[i] = internal[i] - base_load[i];
    const std::size_t top = 6u * Elements;
    const double root_reaction_x = reaction[0];
    const double root_reaction_y = reaction[1];
    const double root_reaction_z = reaction[2];
    const double top_reaction_x = reaction[top];
    const double top_reaction_y = reaction[top + 1u];
    double total_external_x = 0.0;
    double total_external_y = 0.0;
    double total_external_z = 0.0;
    double total_fixed_reaction_x = 0.0;
    double total_fixed_reaction_y = 0.0;
    double total_fixed_reaction_z = 0.0;
    for (std::size_t node = 0; node <= Elements; ++node) {
      const std::size_t dof = 6u * node;
      total_external_x += base_load[dof];
      total_external_y += base_load[dof + 1u];
      total_external_z += base_load[dof + 2u];
    }
    total_fixed_reaction_x = root_reaction_x + top_reaction_x;
    total_fixed_reaction_y = root_reaction_y + top_reaction_y;
    total_fixed_reaction_z = root_reaction_z;
    const double global_balance_x = total_external_x + total_fixed_reaction_x;
    const double global_balance_y = total_external_y + total_fixed_reaction_y;
    const double global_balance_z = total_external_z + total_fixed_reaction_z;
    const double global_balance_norm = std::sqrt(
        global_balance_x * global_balance_x + global_balance_y * global_balance_y +
        global_balance_z * global_balance_z);
    const double prestretch_top_z_m = state.q[top + 2u];
    const double prestretch_delta_m = prestretch_top_z_m - model.length_m;
    const auto free = free_y_dof(model);
    const cfd_ancf::Matrix mass = select(state.mass, free);
    const cfd_ancf::Matrix stiffness = select(tangent, free);
    const cfd_ancf::Matrix lower = cholesky_lower(mass);
    const cfd_ancf::Matrix inverse = inverse_lower(lower);
    const cfd_ancf::Matrix standard = multiply(multiply(inverse, stiffness), transpose(inverse));
    const EigenSystem eigen = jacobi_symmetric(standard);
    if (eigen.values.size() < Modes) throw std::runtime_error("D_MODAL_NONPOSITIVE_EIGENVALUE");

    std::vector<std::vector<double>> modes;
    std::vector<double> lambdas;
    for (std::size_t column = 0; column < eigen.values.size() && modes.size() < Modes; ++column) {
      if (!std::isfinite(eigen.values[column]) || eigen.values[column] <= 0.0)
        throw std::runtime_error("D_MODAL_NONPOSITIVE_EIGENVALUE");
      std::vector<double> transformed = extract_column(eigen.vectors, column);
      std::vector<double> mode = multiply(transpose(inverse), transformed);
      const double mass_norm = std::sqrt(dot(mode, multiply(mass, mode)));
      if (!std::isfinite(mass_norm) || mass_norm <= 0.0) throw std::runtime_error("D_NONFINITE_RESULT");
      for (double& value : mode) value /= mass_norm;
      modes.push_back(mode);
      lambdas.push_back(eigen.values[column]);
    }
    if (modes.size() != Modes) throw std::runtime_error("D_MODAL_NONPOSITIVE_EIGENVALUE");

    cfd_ancf::Matrix phi(mass.rows, Modes);
    double maximum_relative_error = 0.0;
    double sum_relative_error_squared = 0.0;
    std::vector<double> current_frequency(Modes), relative_error(Modes), eigen_residual(Modes);
    for (std::size_t mode_index = 0; mode_index < Modes; ++mode_index) {
      for (std::size_t row = 0; row < mass.rows; ++row) phi(row, mode_index) = modes[mode_index][row];
      current_frequency[mode_index] = std::sqrt(lambdas[mode_index]) / (2.0 * Pi);
      relative_error[mode_index] =
          std::abs(current_frequency[mode_index] - ReferenceFrequencies[mode_index]) /
          std::abs(ReferenceFrequencies[mode_index]);
      maximum_relative_error = (std::max)(maximum_relative_error, relative_error[mode_index]);
      sum_relative_error_squared += relative_error[mode_index] * relative_error[mode_index];
      const std::vector<double> left = multiply(stiffness, modes[mode_index]);
      const std::vector<double> right = multiply(mass, modes[mode_index]);
      std::vector<double> residual(left.size());
      for (std::size_t row = 0; row < residual.size(); ++row)
        residual[row] = left[row] - lambdas[mode_index] * right[row];
      eigen_residual[mode_index] = norm2(residual) /
          (std::max)((std::max)(norm2(left), std::abs(lambdas[mode_index]) * norm2(right)), 1.0e-300);
      if (relative_error[mode_index] > FrequencyTolerance || eigen_residual[mode_index] > EigenResidualTolerance)
        throw std::runtime_error("D_MODAL_FREQUENCY_FAIL");
    }
    cfd_ancf::Matrix gram = multiply(transpose(phi), multiply(mass, phi));
    double orthogonality_error = 0.0;
    for (std::size_t row = 0; row < Modes; ++row)
      for (std::size_t col = 0; col < Modes; ++col) {
        const double difference = gram(row, col) - (row == col ? 1.0 : 0.0);
        orthogonality_error += difference * difference;
      }
    orthogonality_error = std::sqrt(orthogonality_error);
    if (orthogonality_error > MOrthogonalityTolerance)
      throw std::runtime_error("D_M_ORTHOGONALITY_FAIL");

    write_vector(argv[4], state.q);
    write_matrix(argv[5], state.mass);
    write_matrix(argv[6], mass);
    write_matrix(argv[7], tangent);
    write_matrix(argv[8], stiffness);
    write_indices(argv[9], free);

    std::ofstream modes_out(argv[2], std::ios::binary | std::ios::trunc);
    if (!modes_out) throw std::runtime_error("cannot write mode CSV");
    modes_out << "mode,reference_hz,current_hz,absolute_error_hz,relative_error,eigenvalue,residual\n";
    modes_out << std::setprecision(17);
    for (std::size_t i = 0; i < Modes; ++i)
      modes_out << (i + 1) << ',' << ReferenceFrequencies[i] << ',' << current_frequency[i] << ','
                << std::abs(current_frequency[i] - ReferenceFrequencies[i]) << ',' << relative_error[i]
                << ',' << lambdas[i] << ',' << eigen_residual[i] << '\n';

    std::ofstream reconstruction(argv[3], std::ios::binary | std::ios::trunc);
    if (!reconstruction) throw std::runtime_error("cannot write reconstruction CSV");
    reconstruction << "field,value,classification\n"
                   << "length_m,50.0,PERSISTED_EXACT\n"
                   << "diameter_m,1.0,PERSISTED_EXACT\n"
                   << "inner_diameter_m,0.9,PERSISTED_EXACT\n"
                   << "elements,16,PERSISTED_EXACT\n"
                   << "top_tension_N,2179104.0029808935,PERSISTED_EXACT\n"
                   << "E_Pa,3227125779.2218256,PERSISTED_EXACT\n"
                   << "material_density_kgpm3,26315.789473684214,PERSISTED_EXACT\n"
                   << "fluid_density_kgpm3,1000.0,PERSISTED_EXACT\n"
                   << "gravity_mps2,9.81,PERSISTED_EXACT\n"
                   << "mass_gauss_order,5,PERSISTED_EXACT\n"
                   << "internal_gauss_order,3,PERSISTED_EXACT\n"
                   << "static_load_steps,40,PERSISTED_EXACT\n"
                   << "static_relaxation,0.8,PERSISTED_EXACT\n"
                   << "free_dof_contract,transverse_y_position_and_gradient_with_endpoint_y_positions_fixed,RECONSTRUCTED_FROM_FROZEN_SOURCE\n"
                   << "reference_frequencies_hz,matlab_reference.json.modal.modes[1:6],PERSISTED_EXACT\n";

    std::cout << std::setprecision(17);
    std::cout << "status PASS\n"
              << "elements " << Elements << " ndof " << model.ndof() << " free_dof_count " << free.size() << '\n'
              << "static_converged " << (static_diag.converged ? 1 : 0)
              << " static_iterations " << static_diag.iterations
              << " static_residual " << static_diag.residual
              << " residual_scale " << static_diag.residual_scale
              << " normalized_residual " << normalized_static_residual
              << " max_fixed_error " << max_fixed_error
              << " root_reaction_xyz " << root_reaction_x << ',' << root_reaction_y << ',' << root_reaction_z
              << " top_reaction_xy " << top_reaction_x << ',' << top_reaction_y
              << " global_balance_xyz " << global_balance_x << ',' << global_balance_y << ',' << global_balance_z
              << " global_balance_norm " << global_balance_norm
              << " prestretch_top_z_m " << prestretch_top_z_m
              << " prestretch_delta_m " << prestretch_delta_m << '\n'
              << "mass_rows " << state.mass.rows << " mass_cols " << state.mass.cols
              << " mass_ff_rows " << mass.rows << " mass_ff_cols " << mass.cols
              << " mass_symmetry " << symmetry_error(mass)
              << " tangent_rows " << tangent.rows << " tangent_cols " << tangent.cols
              << " tangent_ff_rows " << stiffness.rows << " tangent_ff_cols " << stiffness.cols
              << " tangent_symmetry " << symmetry_error(stiffness)
              << " mass_frobenius " << frobenius(mass)
              << " tangent_ff_frobenius " << frobenius(stiffness) << '\n';
    for (std::size_t i = 0; i < Modes; ++i)
      std::cout << "mode " << (i + 1) << " reference_hz " << ReferenceFrequencies[i]
                << " current_hz " << current_frequency[i]
                << " absolute_error_hz " << std::abs(current_frequency[i] - ReferenceFrequencies[i])
                << " relative_error " << relative_error[i]
                << " eigenvalue " << lambdas[i]
                << " eigen_residual " << eigen_residual[i] << '\n';
    std::cout << "max_relative_frequency_error " << maximum_relative_error
              << " rms_relative_frequency_error " << std::sqrt(sum_relative_error_squared / Modes)
              << " M_orthogonality_error " << orthogonality_error << '\n';
    std::cout << "zero_damping alpha 0 beta 0\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
