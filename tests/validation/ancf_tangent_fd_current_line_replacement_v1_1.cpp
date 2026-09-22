#include "ancf_kernel.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <exception>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

namespace {

using cfd_ancf::Matrix;
using cfd_ancf::Model;

constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr double kLengthScale = 10.0;
constexpr double kGradientScale = 1.0;
constexpr double kFullTolerance = 1.0e-7;
constexpr double kDirectionalTolerance = 1.0e-7;
constexpr double kSymmetryTolerance = 1.0e-14;
constexpr double kScaleFloor = 1.0;
const std::array<double, 13> kH = {1.0e-2, 3.0e-3, 1.0e-3, 3.0e-4, 1.0e-4,
                                   3.0e-5, 1.0e-5, 3.0e-6, 1.0e-6,
                                   3.0e-7, 1.0e-7, 3.0e-8, 1.0e-8};

struct FullRow {
  double h = 0.0;
  double exact_norm = 0.0;
  double fd_norm = 0.0;
  double error_norm = 0.0;
  double relative_error = 0.0;
  double max_abs_entry_error = 0.0;
  double max_scaled_entry_error = 0.0;
};

struct DirectionRow {
  std::string direction;
  double h = 0.0;
  double exact_norm = 0.0;
  double fd_norm = 0.0;
  double error_norm = 0.0;
  double relative_error = 0.0;
};

bool finite(double value) { return std::isfinite(value); }

bool finite_vector(const std::vector<double>& values) {
  return std::all_of(values.begin(), values.end(), finite);
}

bool finite_matrix(const Matrix& value) {
  return std::all_of(value.data.begin(), value.data.end(), finite);
}

double norm2(const std::vector<double>& values) {
  long double sum = 0.0L;
  for (double value : values) sum += static_cast<long double>(value) * value;
  return std::sqrt(static_cast<double>(sum));
}

double frobenius(const Matrix& value) {
  long double sum = 0.0L;
  for (double value : value.data) sum += static_cast<long double>(value) * value;
  return std::sqrt(static_cast<double>(sum));
}

Matrix difference(const Matrix& left, const Matrix& right) {
  Matrix result(left.rows, left.cols);
  for (std::size_t index = 0; index < result.data.size(); ++index)
    result.data[index] = left.data[index] - right.data[index];
  return result;
}

std::vector<double> difference(const std::vector<double>& left,
                               const std::vector<double>& right) {
  std::vector<double> result(left.size(), 0.0);
  for (std::size_t index = 0; index < result.size(); ++index)
    result[index] = left[index] - right[index];
  return result;
}

std::vector<double> multiply(const Matrix& matrix, const std::vector<double>& vector) {
  std::vector<double> result(matrix.rows, 0.0);
  for (std::size_t row = 0; row < matrix.rows; ++row)
    for (std::size_t col = 0; col < matrix.cols; ++col)
      result[row] += matrix(row, col) * vector[col];
  return result;
}

Model make_model() {
  Model model;
  model.length_m = 10.0;
  model.elements = 8;
  model.diameter_m = 0.05;
  model.inner_diameter_m = 0.04;
  model.youngs_modulus_Pa = 2.0e9;
  model.material_density = 4000.0;
  model.fluid_density = 1000.0;
  model.gravity = 9.81;
  model.top_tension_N = 0.0;
  model.slices = 3;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  model.damping_alpha = 0.0;
  model.damping_beta = 0.0;
  model.boundary_contract_id = "tangent_fd_current_line_replacement_v1_1";
  model.fixed_dof.clear();
  model.prescribed_values.clear();
  return model;
}

std::vector<double> make_state(const Model& model) {
  std::vector<double> q(model.ndof(), 0.0);
  for (std::size_t node = 0; node <= model.elements; ++node) {
    const double s = model.length_m * static_cast<double>(node) /
                     static_cast<double>(model.elements);
    const double phase = 2.0 * kPi * s / model.length_m;
    const std::size_t base = 6 * node;
    q[base + 0] = 0.012 * s * s / model.length_m;
    q[base + 1] = 0.007 * std::sin(phase);
    q[base + 2] = 1.015 * s;
    q[base + 3] = 0.024 * s / model.length_m;
    q[base + 4] = 0.007 * (2.0 * kPi / model.length_m) * std::cos(phase);
    q[base + 5] = 1.015;
  }
  return q;
}

std::vector<double> make_direction(const Model& model, int mode) {
  std::vector<double> direction(model.ndof(), 0.0);
  for (std::size_t node = 0; node <= model.elements; ++node) {
    const double node_factor = 1.0 + 0.17 * static_cast<double>(node);
    const std::size_t base = 6 * node;
    if (mode == 1 || mode == 3) {
      direction[base + 0] = 0.13 * node_factor;
      direction[base + 1] = -0.09 * (1.0 + 0.11 * static_cast<double>(node));
      direction[base + 2] = 0.07 * (1.0 - 0.05 * static_cast<double>(node));
    }
    if (mode == 2 || mode == 3) {
      direction[base + 3] = 0.12 * node_factor;
      direction[base + 4] = -0.08 * (1.0 + 0.07 * static_cast<double>(node));
      direction[base + 5] = 0.19 * (1.0 - 0.03 * static_cast<double>(node));
    }
  }
  long double scaled_sum = 0.0L;
  for (std::size_t index = 0; index < direction.size(); ++index) {
    const double scale = index % 6 < 3 ? kLengthScale : kGradientScale;
    scaled_sum += static_cast<long double>(direction[index] / scale) *
                  (direction[index] / scale);
  }
  const double normalization = std::sqrt(static_cast<double>(scaled_sum));
  for (std::size_t index = 0; index < direction.size(); ++index) {
    const double scale = index % 6 < 3 ? kLengthScale : kGradientScale;
    direction[index] = direction[index] / normalization * scale;
  }
  return direction;
}

FullRow full_fd(const std::vector<double>& q, const Matrix& exact,
                const Model& model, double h) {
  Matrix fd(exact.rows, exact.cols);
  for (std::size_t column = 0; column < q.size(); ++column) {
    const double scale = column % 6 < 3 ? kLengthScale : kGradientScale;
    const double delta = h * scale;
    std::vector<double> plus = q;
    std::vector<double> minus = q;
    plus[column] += delta;
    minus[column] -= delta;
    std::vector<double> force_plus;
    std::vector<double> force_minus;
    Matrix tangent_plus;
    Matrix tangent_minus;
    cfd_ancf::internal_force_tangent(plus, model, force_plus, tangent_plus);
    cfd_ancf::internal_force_tangent(minus, model, force_minus, tangent_minus);
    for (std::size_t row = 0; row < q.size(); ++row)
      fd(row, column) = (force_plus[row] - force_minus[row]) / (2.0 * delta);
  }
  const Matrix error = difference(fd, exact);
  FullRow result;
  result.h = h;
  result.exact_norm = frobenius(exact);
  result.fd_norm = frobenius(fd);
  result.error_norm = frobenius(error);
  result.relative_error = result.error_norm / std::max(result.exact_norm, kScaleFloor);
  for (std::size_t index = 0; index < error.data.size(); ++index) {
    result.max_abs_entry_error = std::max(result.max_abs_entry_error, std::abs(error.data[index]));
    result.max_scaled_entry_error = std::max(
        result.max_scaled_entry_error,
        std::abs(error.data[index]) / std::max(1.0, std::abs(exact.data[index])));
  }
  return result;
}

DirectionRow directional_fd(const std::vector<double>& q, const Matrix& exact,
                            const Model& model, const std::vector<double>& direction,
                            const std::string& name, double h) {
  std::vector<double> plus = q;
  std::vector<double> minus = q;
  for (std::size_t index = 0; index < q.size(); ++index) {
    plus[index] += h * direction[index];
    minus[index] -= h * direction[index];
  }
  std::vector<double> force_plus;
  std::vector<double> force_minus;
  Matrix tangent_plus;
  Matrix tangent_minus;
  cfd_ancf::internal_force_tangent(plus, model, force_plus, tangent_plus);
  cfd_ancf::internal_force_tangent(minus, model, force_minus, tangent_minus);
  const std::vector<double> exact_direction = multiply(exact, direction);
  std::vector<double> fd_direction(force_plus.size(), 0.0);
  for (std::size_t index = 0; index < fd_direction.size(); ++index)
    fd_direction[index] = (force_plus[index] - force_minus[index]) / (2.0 * h);
  const std::vector<double> error = difference(fd_direction, exact_direction);
  DirectionRow result;
  result.direction = name;
  result.h = h;
  result.exact_norm = norm2(exact_direction);
  result.fd_norm = norm2(fd_direction);
  result.error_norm = norm2(error);
  result.relative_error = result.error_norm / std::max(result.exact_norm, kScaleFloor);
  return result;
}

bool finite_full(const FullRow& row) {
  return finite(row.h) && finite(row.exact_norm) && finite(row.fd_norm) &&
         finite(row.error_norm) && finite(row.relative_error) &&
         finite(row.max_abs_entry_error) && finite(row.max_scaled_entry_error);
}

bool finite_direction(const DirectionRow& row) {
  return finite(row.h) && finite(row.exact_norm) && finite(row.fd_norm) &&
         finite(row.error_norm) && finite(row.relative_error);
}

void print_full_row(const FullRow& row) {
  std::cout << "{\"h\":" << row.h << ",\"exact_norm\":" << row.exact_norm
            << ",\"fd_norm\":" << row.fd_norm << ",\"error_norm\":"
            << row.error_norm << ",\"relative_error\":" << row.relative_error
            << ",\"max_abs_entry_error\":" << row.max_abs_entry_error
            << ",\"max_scaled_entry_error\":" << row.max_scaled_entry_error << "}";
}

void print_direction_row(const DirectionRow& row) {
  std::cout << "{\"direction\":\"" << row.direction << "\",\"h\":" << row.h
            << ",\"exact_norm\":" << row.exact_norm << ",\"fd_norm\":"
            << row.fd_norm << ",\"error_norm\":" << row.error_norm
            << ",\"relative_error\":" << row.relative_error << "}";
}

}  // namespace

int main() {
  std::cout << std::setprecision(17);
  try {
    const Model model = make_model();
    cfd_ancf::validate_model(model);
    const std::vector<double> q = make_state(model);
    if (!finite_vector(q)) throw std::runtime_error("nonfinite q");

    std::vector<double> force;
    Matrix exact;
    cfd_ancf::internal_force_tangent(q, model, force, exact);
    if (!finite_vector(force) || !finite_matrix(exact))
      throw std::runtime_error("nonfinite production force or tangent");

    Matrix exact_transpose(exact.cols, exact.rows);
    for (std::size_t row = 0; row < exact.rows; ++row)
      for (std::size_t col = 0; col < exact.cols; ++col)
        exact_transpose(col, row) = exact(row, col);
    const double exact_norm = frobenius(exact);
    const double symmetry_relative =
        frobenius(difference(exact, exact_transpose)) / std::max(exact_norm, kScaleFloor);

    std::vector<FullRow> full_rows;
    for (double h : kH) full_rows.push_back(full_fd(q, exact, model, h));
    const bool full_finite = std::all_of(full_rows.begin(), full_rows.end(), finite_full);
    const auto best_it = std::min_element(
        full_rows.begin(), full_rows.end(),
        [](const FullRow& left, const FullRow& right) {
          return left.relative_error < right.relative_error;
        });
    const std::size_t best_index = static_cast<std::size_t>(best_it - full_rows.begin());
    const bool accuracy_pass = full_finite && best_it->relative_error <= kFullTolerance;

    std::vector<double> observed_slopes;
    for (std::size_t index = 0; index + 1 < full_rows.size(); ++index)
      observed_slopes.push_back(
          std::log(full_rows[index].relative_error / full_rows[index + 1].relative_error) /
          std::log(kH[index] / kH[index + 1]));
    std::size_t current_run = 0;
    std::size_t max_qualifying_run = 0;
    for (double slope : observed_slopes) {
      if (slope >= 1.8 && slope <= 2.2) {
        ++current_run;
        max_qualifying_run = std::max(max_qualifying_run, current_run);
      } else {
        current_run = 0;
      }
    }
    const bool second_order_pass = max_qualifying_run >= 4;

    const std::vector<std::vector<double>> directions = {
        make_direction(model, 1), make_direction(model, 2), make_direction(model, 3)};
    const std::array<std::string, 3> direction_names = {"P1_position", "P2_gradient", "P3_mixed"};
    std::vector<DirectionRow> direction_rows;
    std::array<double, 3> direction_min{};
    std::array<std::size_t, 3> direction_best{};
    bool directional_finite = true;
    bool directional_pass = true;
    for (std::size_t direction = 0; direction < directions.size(); ++direction) {
      for (double h : kH)
        direction_rows.push_back(directional_fd(q, exact, model, directions[direction],
                                                direction_names[direction], h));
      const auto begin = direction_rows.end() - static_cast<std::ptrdiff_t>(kH.size());
      const auto best_direction_it = std::min_element(
          begin, direction_rows.end(),
          [](const DirectionRow& left, const DirectionRow& right) {
            return left.relative_error < right.relative_error;
          });
      direction_min[direction] = best_direction_it->relative_error;
      direction_best[direction] = static_cast<std::size_t>(best_direction_it - begin);
      const bool this_finite = std::all_of(begin, direction_rows.end(), finite_direction);
      directional_finite = directional_finite && this_finite;
      directional_pass = directional_pass && this_finite &&
                         direction_min[direction] <= kDirectionalTolerance;
    }

    const bool symmetry_pass = finite(symmetry_relative) && symmetry_relative <= kSymmetryTolerance;
    const bool pass = accuracy_pass && second_order_pass && directional_pass && symmetry_pass;
    bool tail_increase = false;
    for (std::size_t index = 1; index < full_rows.size(); ++index)
      tail_increase = tail_increase || full_rows[index].relative_error > full_rows[index - 1].relative_error;
    const char* roundoff = tail_increase ? "ERROR_INCREASE_OBSERVED" : "NO_ERROR_INCREASE_TO_1E-8";

    std::cout << "{\"schema_version\":\"ANCF_TANGENT_FD_CURRENT_LINE_REPLACEMENT_V1.1\","
              << "\"status\":\"" << (pass ? "PASS" : "FAIL") << "\","
              << "\"historical_b\":\"PASS_RETAINED_NOT_RECONSTRUCTED\","
              << "\"model\":{\"length_m\":" << model.length_m << ",\"elements\":"
              << model.elements << ",\"diameter_m\":" << model.diameter_m
              << ",\"inner_diameter_m\":" << model.inner_diameter_m
              << ",\"youngs_modulus_Pa\":" << model.youngs_modulus_Pa
              << ",\"damping_alpha\":" << model.damping_alpha
              << ",\"damping_beta\":" << model.damping_beta << "},"
              << "\"q_ndof\":" << q.size() << ",\"q_norm\":" << norm2(q)
              << ",\"force_norm\":" << norm2(force)
              << ",\"exact_tangent_norm\":" << exact_norm
              << ",\"length_scale\":" << kLengthScale
              << ",\"gradient_scale\":" << kGradientScale
              << ",\"h_sequence\":[";
    for (std::size_t index = 0; index < kH.size(); ++index) {
      if (index != 0) std::cout << ",";
      std::cout << kH[index];
    }
    std::cout << "],\"full_matrix_sweep\":[";
    for (std::size_t index = 0; index < full_rows.size(); ++index) {
      if (index != 0) std::cout << ",";
      print_full_row(full_rows[index]);
    }
    std::cout << "],\"best_full_index\":" << best_index
              << ",\"best_full_h\":" << best_it->h
              << ",\"best_full_relative_error\":" << best_it->relative_error
              << ",\"accuracy_pass\":" << (accuracy_pass ? "true" : "false")
              << ",\"observed_slopes\":[";
    for (std::size_t index = 0; index < observed_slopes.size(); ++index) {
      if (index != 0) std::cout << ",";
      std::cout << observed_slopes[index];
    }
    std::cout << "],\"max_qualifying_second_order_transitions\":" << max_qualifying_run
              << ",\"second_order_region_pass\":" << (second_order_pass ? "true" : "false")
              << ",\"roundoff_behavior\":\"" << roundoff << "\",\"directional_sweep\":[";
    for (std::size_t index = 0; index < direction_rows.size(); ++index) {
      if (index != 0) std::cout << ",";
      print_direction_row(direction_rows[index]);
    }
    std::cout << "],\"direction_min_relative_error\":[" << direction_min[0] << ","
              << direction_min[1] << "," << direction_min[2] << "],"
              << "\"direction_best_index\":[" << direction_best[0] << ","
              << direction_best[1] << "," << direction_best[2] << "],"
              << "\"directional_finite\":" << (directional_finite ? "true" : "false")
              << ",\"directional_pass\":" << (directional_pass ? "true" : "false")
              << ",\"symmetry_relative_error\":" << symmetry_relative
              << ",\"symmetry_pass\":" << (symmetry_pass ? "true" : "false")
              << ",\"tolerances\":{\"full_matrix\":" << kFullTolerance
              << ",\"directional\":" << kDirectionalTolerance
              << ",\"symmetry\":" << kSymmetryTolerance
              << ",\"observed_order_low\":1.8,\"observed_order_high\":2.2,"
              << "\"minimum_consecutive_transitions\":4},\"zero_damping\":true,"
              << "\"external_load_in_api\":false,\"production_source_modified\":false,"
              << "\"finite_results\":" << ((full_finite && directional_finite && finite(symmetry_relative)) ? "true" : "false")
              << "}\n";
    return pass ? 0 : 1;
  } catch (const std::exception& error) {
    std::cout << "{\"schema_version\":\"ANCF_TANGENT_FD_CURRENT_LINE_REPLACEMENT_V1.1\","
              << "\"status\":\"ERROR\",\"message\":\"" << error.what() << "\"}\n";
    return 2;
  }
}
