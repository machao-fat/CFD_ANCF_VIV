#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

using cfd_ancf::Matrix;
using cfd_ancf::Model;

constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr double kForceTolerance = 5.0e-12;
constexpr double kTangentTolerance = 5.0e-12;
constexpr double kStressFreeTolerance = 5.0e-12;

struct Vec3 {
  double x = 0.0;
  double y = 0.0;
  double z = 0.0;
};

struct Metrics {
  double original_force_norm = 0.0;
  double transformed_force_norm = 0.0;
  double expected_force_norm = 0.0;
  double force_error_norm = 0.0;
  double force_relative_error = 0.0;
  double original_tangent_norm = 0.0;
  double transformed_tangent_norm = 0.0;
  double expected_tangent_norm = 0.0;
  double tangent_error_norm = 0.0;
  double tangent_relative_error = 0.0;
};

struct StressFreeMetrics {
  double max_abs_force = 0.0;
  double force_norm = 0.0;
  double normalized_force_norm = 0.0;
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

double max_abs(const std::vector<double>& values) {
  double result = 0.0;
  for (double value : values) result = std::max(result, std::abs(value));
  return result;
}

double frobenius(const Matrix& value) {
  long double sum = 0.0L;
  for (double item : value.data) sum += static_cast<long double>(item) * item;
  return std::sqrt(static_cast<double>(sum));
}

Matrix identity(std::size_t n) {
  Matrix result(n, n);
  for (std::size_t i = 0; i < n; ++i) result(i, i) = 1.0;
  return result;
}

Matrix transpose(const Matrix& value) {
  Matrix result(value.cols, value.rows);
  for (std::size_t row = 0; row < value.rows; ++row)
    for (std::size_t col = 0; col < value.cols; ++col)
      result(col, row) = value(row, col);
  return result;
}

Matrix multiply(const Matrix& left, const Matrix& right) {
  Matrix result(left.rows, right.cols);
  for (std::size_t row = 0; row < left.rows; ++row) {
    for (std::size_t col = 0; col < right.cols; ++col) {
      double value = 0.0;
      for (std::size_t inner = 0; inner < left.cols; ++inner)
        value += left(row, inner) * right(inner, col);
      result(row, col) = value;
    }
  }
  return result;
}

std::vector<double> multiply(const Matrix& left, const std::vector<double>& right) {
  std::vector<double> result(left.rows, 0.0);
  for (std::size_t row = 0; row < left.rows; ++row)
    for (std::size_t col = 0; col < left.cols; ++col)
      result[row] += left(row, col) * right[col];
  return result;
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

Matrix rotation_matrix() {
  const Vec3 axis{1.0 / std::sqrt(14.0), 2.0 / std::sqrt(14.0),
                  3.0 / std::sqrt(14.0)};
  const double angle = 0.47;
  const double c = std::cos(angle);
  const double s = std::sin(angle);
  const double one_minus_c = 1.0 - c;
  Matrix result(3, 3);
  result(0, 0) = c + axis.x * axis.x * one_minus_c;
  result(0, 1) = axis.x * axis.y * one_minus_c - axis.z * s;
  result(0, 2) = axis.x * axis.z * one_minus_c + axis.y * s;
  result(1, 0) = axis.y * axis.x * one_minus_c + axis.z * s;
  result(1, 1) = c + axis.y * axis.y * one_minus_c;
  result(1, 2) = axis.y * axis.z * one_minus_c - axis.x * s;
  result(2, 0) = axis.z * axis.x * one_minus_c - axis.y * s;
  result(2, 1) = axis.z * axis.y * one_minus_c + axis.x * s;
  result(2, 2) = c + axis.z * axis.z * one_minus_c;
  return result;
}

Vec3 apply(const Matrix& rotation, const Vec3& value) {
  return {rotation(0, 0) * value.x + rotation(0, 1) * value.y + rotation(0, 2) * value.z,
          rotation(1, 0) * value.x + rotation(1, 1) * value.y + rotation(1, 2) * value.z,
          rotation(2, 0) * value.x + rotation(2, 1) * value.y + rotation(2, 2) * value.z};
}

double determinant(const Matrix& value) {
  return value(0, 0) * (value(1, 1) * value(2, 2) - value(1, 2) * value(2, 1)) -
         value(0, 1) * (value(1, 0) * value(2, 2) - value(1, 2) * value(2, 0)) +
         value(0, 2) * (value(1, 0) * value(2, 1) - value(1, 1) * value(2, 0));
}

double orthogonality_error(const Matrix& value) {
  const Matrix product = multiply(transpose(value), value);
  double result = 0.0;
  for (std::size_t row = 0; row < 3; ++row) {
    for (std::size_t col = 0; col < 3; ++col) {
      const double expected = row == col ? 1.0 : 0.0;
      result = std::max(result, std::abs(product(row, col) - expected));
    }
  }
  return result;
}

Matrix block_transformation(const Matrix& rotation, std::size_t ndof) {
  Matrix result = identity(ndof);
  const std::size_t nodes = ndof / 6;
  for (std::size_t node = 0; node < nodes; ++node) {
    const std::size_t base = 6 * node;
    for (std::size_t block : {std::size_t(0), std::size_t(3)}) {
      for (std::size_t row = 0; row < 3; ++row) {
        for (std::size_t col = 0; col < 3; ++col)
          result(base + block + row, base + block + col) = rotation(row, col);
      }
    }
  }
  return result;
}

std::vector<double> make_nontrivial_state(const Model& model) {
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

std::vector<double> transform_state(const std::vector<double>& q,
                                     const Matrix& rotation,
                                     const Vec3& translation,
                                     bool rotate,
                                     bool translate) {
  std::vector<double> result(q.size(), 0.0);
  for (std::size_t node = 0; node < q.size() / 6; ++node) {
    const std::size_t base = 6 * node;
    const Vec3 position{q[base + 0], q[base + 1], q[base + 2]};
    const Vec3 gradient{q[base + 3], q[base + 4], q[base + 5]};
    Vec3 transformed_position = rotate ? apply(rotation, position) : position;
    const Vec3 transformed_gradient = rotate ? apply(rotation, gradient) : gradient;
    if (translate) {
      transformed_position.x += translation.x;
      transformed_position.y += translation.y;
      transformed_position.z += translation.z;
    }
    result[base + 0] = transformed_position.x;
    result[base + 1] = transformed_position.y;
    result[base + 2] = transformed_position.z;
    result[base + 3] = transformed_gradient.x;
    result[base + 4] = transformed_gradient.y;
    result[base + 5] = transformed_gradient.z;
  }
  return result;
}

Metrics evaluate(const std::vector<double>& original_q,
                 const std::vector<double>& transformed_q,
                 const Matrix& transformation,
                 const Model& model) {
  std::vector<double> original_force;
  std::vector<double> transformed_force;
  Matrix original_tangent;
  Matrix transformed_tangent;
  cfd_ancf::internal_force_tangent(original_q, model, original_force, original_tangent);
  cfd_ancf::internal_force_tangent(transformed_q, model, transformed_force, transformed_tangent);
  const std::vector<double> expected_force = multiply(transformation, original_force);
  const Matrix expected_tangent = multiply(multiply(transformation, original_tangent),
                                           transpose(transformation));
  const std::vector<double> force_error = difference(transformed_force, expected_force);
  const Matrix tangent_error = difference(transformed_tangent, expected_tangent);
  Metrics result;
  result.original_force_norm = norm2(original_force);
  result.transformed_force_norm = norm2(transformed_force);
  result.expected_force_norm = norm2(expected_force);
  result.force_error_norm = norm2(force_error);
  result.force_relative_error = result.force_error_norm / std::max(1.0, result.expected_force_norm);
  result.original_tangent_norm = frobenius(original_tangent);
  result.transformed_tangent_norm = frobenius(transformed_tangent);
  result.expected_tangent_norm = frobenius(expected_tangent);
  result.tangent_error_norm = frobenius(tangent_error);
  result.tangent_relative_error = result.tangent_error_norm / std::max(1.0, result.expected_tangent_norm);
  return result;
}

StressFreeMetrics stress_free(const std::vector<double>& reference_q,
                              const Matrix& rotation,
                              const Vec3& translation,
                              bool rotate,
                              bool translate,
                              const Model& model) {
  std::vector<double> force;
  Matrix tangent;
  cfd_ancf::internal_force_tangent(reference_q, model, force, tangent);
  const std::vector<double> transformed = transform_state(reference_q, rotation, translation, rotate, translate);
  std::vector<double> transformed_force;
  cfd_ancf::internal_force_tangent(transformed, model, transformed_force, tangent);
  StressFreeMetrics result;
  result.max_abs_force = max_abs(transformed_force);
  result.force_norm = norm2(transformed_force);
  result.normalized_force_norm = result.force_norm / std::max(1.0, model.EA());
  return result;
}

bool metrics_finite(const Metrics& value) {
  return finite(value.original_force_norm) && finite(value.transformed_force_norm) &&
         finite(value.expected_force_norm) && finite(value.force_error_norm) &&
         finite(value.force_relative_error) && finite(value.original_tangent_norm) &&
         finite(value.transformed_tangent_norm) && finite(value.expected_tangent_norm) &&
         finite(value.tangent_error_norm) && finite(value.tangent_relative_error);
}

bool stress_finite(const StressFreeMetrics& value) {
  return finite(value.max_abs_force) && finite(value.force_norm) && finite(value.normalized_force_norm);
}

void print_metrics(const char* name, const Metrics& value) {
  std::cout << "\"" << name << "\":{";
  std::cout << "\"original_force_norm\":" << value.original_force_norm << ",";
  std::cout << "\"transformed_force_norm\":" << value.transformed_force_norm << ",";
  std::cout << "\"expected_force_norm\":" << value.expected_force_norm << ",";
  std::cout << "\"force_error_norm\":" << value.force_error_norm << ",";
  std::cout << "\"force_relative_error\":" << value.force_relative_error << ",";
  std::cout << "\"original_tangent_norm\":" << value.original_tangent_norm << ",";
  std::cout << "\"transformed_tangent_norm\":" << value.transformed_tangent_norm << ",";
  std::cout << "\"expected_tangent_norm\":" << value.expected_tangent_norm << ",";
  std::cout << "\"tangent_error_norm\":" << value.tangent_error_norm << ",";
  std::cout << "\"tangent_relative_error\":" << value.tangent_relative_error << "}";
}

void print_stress(const char* name, const StressFreeMetrics& value) {
  std::cout << "\"" << name << "\":{";
  std::cout << "\"max_abs_force\":" << value.max_abs_force << ",";
  std::cout << "\"force_norm\":" << value.force_norm << ",";
  std::cout << "\"normalized_force_norm\":" << value.normalized_force_norm << "}";
}

}  // namespace

int main() {
  std::cout << std::setprecision(17);
  try {
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
    model.boundary_contract_id = "objectivity_current_line_replacement_v1";
    model.fixed_dof.clear();
    model.prescribed_values.clear();
    cfd_ancf::validate_model(model);

    const Matrix rotation = rotation_matrix();
    const Vec3 translation{0.37, -0.23, 0.41};
    const Matrix block_rotation = block_transformation(rotation, model.ndof());
    const Matrix identity_transformation = identity(model.ndof());
    const auto reference_state = cfd_ancf::make_reference_state(model);
    const std::vector<double> q = make_nontrivial_state(model);
    const std::vector<double> q_translation = transform_state(q, rotation, translation, false, true);
    const std::vector<double> q_rotation = transform_state(q, rotation, translation, true, false);
    const std::vector<double> q_combined = transform_state(q, rotation, translation, true, true);

    const Metrics translation_metrics = evaluate(q, q_translation, identity_transformation, model);
    const Metrics rotation_metrics = evaluate(q, q_rotation, block_rotation, model);
    const Metrics combined_metrics = evaluate(q, q_combined, block_rotation, model);
    const StressFreeMetrics stress_translation =
        stress_free(reference_state.q, rotation, translation, false, true, model);
    const StressFreeMetrics stress_rotation =
        stress_free(reference_state.q, rotation, translation, true, false, model);
    const StressFreeMetrics stress_combined =
        stress_free(reference_state.q, rotation, translation, true, true, model);

    const double rotation_orthogonality_error = orthogonality_error(rotation);
    const double rotation_determinant = determinant(rotation);
    const bool finite_results = metrics_finite(translation_metrics) && metrics_finite(rotation_metrics) &&
                                 metrics_finite(combined_metrics) && stress_finite(stress_translation) &&
                                 stress_finite(stress_rotation) && stress_finite(stress_combined);
    const bool rotation_valid = finite(rotation_orthogonality_error) && finite(rotation_determinant) &&
                                rotation_orthogonality_error <= 1.0e-14 &&
                                std::abs(rotation_determinant - 1.0) <= 1.0e-14;
    const bool covariance_pass =
        translation_metrics.force_relative_error <= kForceTolerance &&
        translation_metrics.tangent_relative_error <= kTangentTolerance &&
        rotation_metrics.force_relative_error <= kForceTolerance &&
        rotation_metrics.tangent_relative_error <= kTangentTolerance &&
        combined_metrics.force_relative_error <= kForceTolerance &&
        combined_metrics.tangent_relative_error <= kTangentTolerance;
    const bool stress_free_pass =
        stress_translation.normalized_force_norm <= kStressFreeTolerance &&
        stress_rotation.normalized_force_norm <= kStressFreeTolerance &&
        stress_combined.normalized_force_norm <= kStressFreeTolerance;
    const bool pass = finite_results && rotation_valid && covariance_pass && stress_free_pass;

    std::cout << "{\"schema_version\":\"ANCF_OBJECTIVITY_CURRENT_LINE_REPLACEMENT_V1\",";
    std::cout << "\"status\":\"" << (pass ? "PASS" : "FAIL") << "\",";
    std::cout << "\"production_api\":{\"internal_force_tangent\":true,\"energy_api\":false},";
    std::cout << "\"model\":{\"length_m\":" << model.length_m << ",\"elements\":" << model.elements
              << ",\"diameter_m\":" << model.diameter_m << ",\"inner_diameter_m\":"
              << model.inner_diameter_m << ",\"youngs_modulus_Pa\":" << model.youngs_modulus_Pa
              << ",\"top_tension_N\":" << model.top_tension_N << ",\"damping_alpha\":"
              << model.damping_alpha << ",\"damping_beta\":" << model.damping_beta << "},";
    std::cout << "\"rotation\":{\"axis\":[0.2672612419124244,0.5345224838248488,0.8017837257372732],"
              << "\"angle_rad\":0.46999999999999997,\"orthogonality_error\":"
              << rotation_orthogonality_error << ",\"determinant\":" << rotation_determinant << "},";
    std::cout << "\"translation\":[0.37,-0.23,0.41],";
    print_metrics("translation_metrics", translation_metrics);
    std::cout << ",";
    print_metrics("rotation_metrics", rotation_metrics);
    std::cout << ",";
    print_metrics("combined_metrics", combined_metrics);
    std::cout << ",";
    print_stress("stress_free_translation", stress_translation);
    std::cout << ",";
    print_stress("stress_free_rotation", stress_rotation);
    std::cout << ",";
    print_stress("stress_free_combined", stress_combined);
    std::cout << ",\"tolerances\":{\"force_relative\":" << kForceTolerance
              << ",\"tangent_relative\":" << kTangentTolerance
              << ",\"stress_free_normalized\":" << kStressFreeTolerance << "},";
    std::cout << "\"energy_invariance\":\"NOT_AVAILABLE_PRODUCTION_API\",\"zero_damping\":true,";
    std::cout << "\"finite_results\":" << (finite_results ? "true" : "false") << ",";
    std::cout << "\"rotation_valid\":" << (rotation_valid ? "true" : "false") << ",";
    std::cout << "\"force_tangent_covariance_pass\":" << (covariance_pass ? "true" : "false") << ",";
    std::cout << "\"stress_free_pass\":" << (stress_free_pass ? "true" : "false") << "}\n";
    return pass ? 0 : 1;
  } catch (const std::exception& error) {
    std::cout << "{\"schema_version\":\"ANCF_OBJECTIVITY_CURRENT_LINE_REPLACEMENT_V1\","
              << "\"status\":\"ERROR\",\"message\":\"" << error.what() << "\"}\n";
    return 2;
  }
}
