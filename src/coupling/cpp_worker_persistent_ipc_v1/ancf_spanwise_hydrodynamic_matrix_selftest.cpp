#include "ancf_kernel.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using cfd_ancf::Matrix;
using cfd_ancf::Model;
using cfd_ancf::SpanwiseHydrodynamicRegion;

struct Metrics {
  std::size_t dimension = 0;
  double max_abs_error = 0.0;
  double max_rel_error = 0.0;
  double symmetry_error = 0.0;
  double quadratic_form_min = 0.0;
};

struct Record {
  std::string name;
  Metrics metrics;
  bool pass = false;
  std::string detail;
};

Model model_with_elements(std::size_t elements) {
  Model model;
  model.length_m = 8.0;
  model.elements = elements;
  model.slices = 3;
  model.top_tension_N = 0.0;
  model.newton_tolerance = 1.0e-8;
  return model;
}

SpanwiseHydrodynamicRegion region(
    double left, double right, std::array<double, 3> mass,
    std::array<double, 3> damping) {
  SpanwiseHydrodynamicRegion value;
  value.s_min_m = left;
  value.s_max_m = right;
  value.added_mass_per_length_kg_m = mass;
  value.linear_damping_per_length_Ns_m2 = damping;
  return value;
}

double max_abs(const Matrix& matrix) {
  double result = 0.0;
  for (double value : matrix.data) result = std::max(result, std::abs(value));
  return result;
}

double max_difference(const Matrix& left, const Matrix& right, Metrics& metrics) {
  if (left.rows != right.rows || left.cols != right.cols)
    throw std::runtime_error("matrix dimensions differ");
  metrics.dimension = left.rows;
  double max_abs_error = 0.0;
  double max_rel_error = 0.0;
  const double reference_scale = std::max(1.0, max_abs(right));
  for (std::size_t index = 0; index < left.data.size(); ++index) {
    const double error = std::abs(left.data[index] - right.data[index]);
    max_abs_error = std::max(max_abs_error, error);
    // Relative error is only meaningful on material reference entries.
    // Near-zero blocks are controlled by the independent absolute-error gate;
    // assigning them a pseudo-relative scale would report a harmless ulp as a
    // misleading large percentage.
    if (std::abs(right.data[index]) >= 1.0e-8 * reference_scale)
      max_rel_error = std::max(max_rel_error, error / std::abs(right.data[index]));
  }
  metrics.max_abs_error = std::max(metrics.max_abs_error, max_abs_error);
  metrics.max_rel_error = std::max(metrics.max_rel_error, max_rel_error);
  return max_abs_error;
}

double symmetry_error(const Matrix& matrix) {
  if (matrix.rows != matrix.cols) throw std::runtime_error("matrix is not square");
  double result = 0.0;
  for (std::size_t row = 0; row < matrix.rows; ++row)
    for (std::size_t col = row + 1; col < matrix.cols; ++col)
      result = std::max(result, std::abs(matrix(row, col) - matrix(col, row)));
  return result;
}

double quadratic(const Matrix& matrix, const std::vector<double>& vector) {
  if (matrix.rows != matrix.cols || matrix.cols != vector.size())
    throw std::runtime_error("quadratic dimensions differ");
  double result = 0.0;
  for (std::size_t row = 0; row < matrix.rows; ++row)
    for (std::size_t col = 0; col < matrix.cols; ++col)
      result += vector[row] * matrix(row, col) * vector[col];
  return result;
}

std::vector<double> deterministic_vector(std::size_t n, int seed) {
  std::vector<double> values(n);
  for (std::size_t index = 0; index < n; ++index) {
    values[index] = std::sin(0.17 * static_cast<double>((seed + 1) * (index + 1))) +
                    0.25 * std::cos(0.31 * static_cast<double>(seed + index + 1));
  }
  return values;
}

double roundoff_bound(const Matrix& matrix, const std::vector<double>& vector) {
  double vector_square = 0.0;
  for (double value : vector) vector_square += value * value;
  return 256.0 * std::numeric_limits<double>::epsilon() *
         std::max(1.0, max_abs(matrix)) * std::max(1.0, vector_square) *
         static_cast<double>(matrix.rows);
}

// Test-only independent Gauss-8 oracle. It does not call production shape(),
// block_matrix(), gauss(), or either M1 assembler.
std::array<double, 4> oracle_shape(double x, double length) {
  const double xi = x / length;
  return {1.0 - 3.0 * xi * xi + 2.0 * xi * xi * xi,
          length * (xi - 2.0 * xi * xi + xi * xi * xi),
          3.0 * xi * xi - 2.0 * xi * xi * xi,
          length * (-xi * xi + xi * xi * xi)};
}

double oracle_n(const std::array<double, 4>& shape, std::size_t component, std::size_t column) {
  return column % 3u == component ? shape[column / 3u] : 0.0;
}

const std::array<double, 8>& gauss8_points() {
  static const std::array<double, 8> value{
      -0.96028985649753623168, -0.79666647741362673959,
      -0.52553240991632898582, -0.18343464249564980494,
       0.18343464249564980494,  0.52553240991632898582,
       0.79666647741362673959,  0.96028985649753623168};
  return value;
}

const std::array<double, 8>& gauss8_weights() {
  static const std::array<double, 8> value{
      0.10122853629037625915, 0.22238103445337447054,
      0.31370664587788728734, 0.36268378337836198297,
      0.36268378337836198297, 0.31370664587788728734,
      0.22238103445337447054, 0.10122853629037625915};
  return value;
}

Matrix independent_oracle(const Model& model,
                          const std::vector<SpanwiseHydrodynamicRegion>& regions,
                          bool mass) {
  const std::size_t n = model.ndof();
  Matrix result(n, n);
  const double element_length = model.length_m / static_cast<double>(model.elements);
  for (std::size_t element = 0; element < model.elements; ++element) {
    const double e0 = static_cast<double>(element) * element_length;
    const double e1 = e0 + element_length;
    for (const auto& item : regions) {
      const std::array<double, 3>& coefficient =
          mass ? item.added_mass_per_length_kg_m : item.linear_damping_per_length_Ns_m2;
      const double left = std::max(e0, item.s_min_m);
      const double right = std::min(e1, item.s_max_m);
      if (right <= left) continue;
      for (std::size_t point = 0; point < gauss8_points().size(); ++point) {
        const double s = 0.5 * (left + right) + 0.5 * (right - left) * gauss8_points()[point];
        const auto shape = oracle_shape(s - e0, element_length);
        const double weight = 0.5 * (right - left) * gauss8_weights()[point];
        for (std::size_t row = 0; row < 12; ++row) {
          for (std::size_t col = 0; col < 12; ++col) {
            double value = 0.0;
            for (std::size_t component = 0; component < 3; ++component)
              value += coefficient[component] * oracle_n(shape, component, row) *
                       oracle_n(shape, component, col);
            result(6 * element + row, 6 * element + col) += weight * value;
          }
        }
      }
    }
  }
  return result;
}

Matrix matrix_sum(const Matrix& left, const Matrix& right) {
  if (left.rows != right.rows || left.cols != right.cols)
    throw std::runtime_error("matrix sum dimensions differ");
  Matrix result(left.rows, left.cols);
  for (std::size_t index = 0; index < result.data.size(); ++index)
    result.data[index] = left.data[index] + right.data[index];
  return result;
}

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

template <typename Function>
void run(std::vector<Record>& records, const std::string& name, Function&& function) {
  Record record;
  record.name = name;
  try {
    record.metrics = function();
    record.pass = true;
    record.detail = "pass";
  } catch (const std::exception& error) {
    record.pass = false;
    record.detail = error.what();
  }
  records.push_back(std::move(record));
}

bool exact_zero(const Matrix& matrix) {
  return std::all_of(matrix.data.begin(), matrix.data.end(), [](double value) { return value == 0.0; });
}

void json_string(std::ostream& stream, const std::string& value) {
  stream << '"';
  for (char character : value) {
    if (character == '"' || character == '\\') stream << '\\';
    stream << character;
  }
  stream << '"';
}

void emit_json(const std::vector<Record>& records) {
  std::cout << std::setprecision(17);
  std::cout << "{\n  \"suite\": \"ancf_spanwise_hydrodynamic_matrix_selftest_v1\",\n"
            << "  \"tests\": [\n";
  for (std::size_t index = 0; index < records.size(); ++index) {
    const Record& record = records[index];
    std::cout << "    {\"name\":"; json_string(std::cout, record.name);
    std::cout << ",\"matrix_dimension\":" << record.metrics.dimension
              << ",\"max_abs_error\":" << record.metrics.max_abs_error
              << ",\"max_rel_error\":" << record.metrics.max_rel_error
              << ",\"symmetry_error\":" << record.metrics.symmetry_error
              << ",\"quadratic_form_min\":" << record.metrics.quadratic_form_min
              << ",\"pass\":" << (record.pass ? "true" : "false") << ",\"detail\":";
    json_string(std::cout, record.detail);
    std::cout << "}" << (index + 1 == records.size() ? "\n" : ",\n");
  }
  const bool pass = std::all_of(records.begin(), records.end(),
                                [](const Record& record) { return record.pass; });
  std::cout << "  ],\n  \"status\": \"" << (pass ? "PASS" : "DO_NOT_PASS") << "\"\n}\n";
}

}  // namespace

int main() {
  std::vector<Record> records;

  run(records, "A_empty_regions", [] {
    const Model model = model_with_elements(4);
    const Matrix mass = cfd_ancf::assemble_spanwise_added_mass(model, {});
    const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, {});
    require(mass.rows == model.ndof() && damping.rows == model.ndof(), "wrong empty matrix dimension");
    require(exact_zero(mass) && exact_zero(damping), "empty regions are not exact zero");
    Metrics metrics; metrics.dimension = mass.rows; return metrics;
  });

  run(records, "B_zero_coefficient_region", [] {
    const Model model = model_with_elements(4);
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(1.0, 7.0, {0.0, 0.0, 0.0}, {0.0, 0.0, 0.0})};
    const Matrix mass = cfd_ancf::assemble_spanwise_added_mass(model, regions);
    const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, regions);
    require(exact_zero(mass) && exact_zero(damping), "zero coefficient region is not exact zero");
    Metrics metrics; metrics.dimension = mass.rows; return metrics;
  });

  run(records, "C_full_span_isotropic_mass_against_production_consistent_mass", [] {
    Model model = model_with_elements(4);
    constexpr double m0 = 7.25;
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(0.0, model.length_m, {m0, m0, m0}, {0.0, 0.0, 0.0})};
    const Matrix actual = cfd_ancf::assemble_spanwise_added_mass(model, regions);
    model.section_property_mode = cfd_ancf::SectionPropertyMode::ExplicitSectionProperties;
    model.explicit_EA_N = 1.0e6;
    model.explicit_EI_Nm2 = 1.0e3;
    model.explicit_mass_per_length_kg_m = m0;
    model.explicit_displaced_area_m2 = 1.0;
    const Matrix expected = cfd_ancf::make_reference_state(model).mass;
    Metrics metrics;
    max_difference(actual, expected, metrics);
    if (metrics.max_abs_error > 2.0e-12 || metrics.max_rel_error > 2.0e-11)
      throw std::runtime_error("full-span isotropic mass differs: abs=" + std::to_string(metrics.max_abs_error) +
                               " rel=" + std::to_string(metrics.max_rel_error));
    return metrics;
  });

  run(records, "D_full_span_anisotropic_mass_component_audit", [] {
    Model model = model_with_elements(4);
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(0.0, model.length_m, {2.0, 3.0, 0.0}, {0.0, 0.0, 0.0})};
    const Matrix actual = cfd_ancf::assemble_spanwise_added_mass(model, regions);
    model.section_property_mode = cfd_ancf::SectionPropertyMode::ExplicitSectionProperties;
    model.explicit_EA_N = 1.0e6; model.explicit_EI_Nm2 = 1.0e3;
    model.explicit_mass_per_length_kg_m = 1.0; model.explicit_displaced_area_m2 = 1.0;
    const Matrix scalar = cfd_ancf::make_reference_state(model).mass;
    Matrix expected(actual.rows, actual.cols);
    for (std::size_t row = 0; row < expected.rows; ++row) {
      for (std::size_t col = 0; col < expected.cols; ++col) {
        if (row % 3u == col % 3u) {
          const std::size_t component = row % 3u;
          const double coefficient = component == 0 ? 2.0 : (component == 1 ? 3.0 : 0.0);
          expected(row, col) = coefficient * scalar(row, col);
        }
      }
    }
    Metrics metrics;
    max_difference(actual, expected, metrics);
    if (metrics.max_abs_error > 2.0e-12 || metrics.max_rel_error > 2.0e-11)
      throw std::runtime_error("anisotropic component audit failed: abs=" + std::to_string(metrics.max_abs_error) +
                               " rel=" + std::to_string(metrics.max_rel_error));
    return metrics;
  });

  run(records, "E_element_aligned_partial_region", [] {
    const Model model = model_with_elements(4);
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(2.0, 6.0, {1.25, 2.5, 0.75}, {4.0, 1.0, 0.5})};
    const Matrix mass = cfd_ancf::assemble_spanwise_added_mass(model, regions);
    const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, regions);
    Metrics metrics;
    max_difference(mass, independent_oracle(model, regions, true), metrics);
    max_difference(damping, independent_oracle(model, regions, false), metrics);
    if (metrics.max_abs_error > 2.0e-12 || metrics.max_rel_error > 2.0e-11)
      throw std::runtime_error("element-aligned integration differs: abs=" + std::to_string(metrics.max_abs_error) +
                               " rel=" + std::to_string(metrics.max_rel_error));
    return metrics;
  });

  run(records, "F_element_cutting_partial_region", [] {
    const Model model = model_with_elements(4);
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(1.15, 6.35, {1.25, 2.5, 0.75}, {4.0, 1.0, 0.5})};
    const Matrix mass = cfd_ancf::assemble_spanwise_added_mass(model, regions);
    const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, regions);
    Metrics metrics;
    max_difference(mass, independent_oracle(model, regions, true), metrics);
    max_difference(damping, independent_oracle(model, regions, false), metrics);
    if (metrics.max_abs_error > 2.0e-12 || metrics.max_rel_error > 2.0e-11)
      throw std::runtime_error("element-cutting integration differs: abs=" + std::to_string(metrics.max_abs_error) +
                               " rel=" + std::to_string(metrics.max_rel_error));
    return metrics;
  });

  run(records, "G_multiple_disjoint_regions_additivity", [] {
    const Model model = model_with_elements(4);
    const auto first = region(0.25, 2.75, {1.0, 2.0, 0.5}, {3.0, 1.0, 2.0});
    const auto second = region(5.25, 7.5, {0.5, 1.5, 2.0}, {1.0, 4.0, 0.5});
    const std::vector<SpanwiseHydrodynamicRegion> all{first, second};
    Metrics metrics;
    max_difference(cfd_ancf::assemble_spanwise_added_mass(model, all),
                   matrix_sum(cfd_ancf::assemble_spanwise_added_mass(model, {first}),
                              cfd_ancf::assemble_spanwise_added_mass(model, {second})), metrics);
    max_difference(cfd_ancf::assemble_spanwise_linear_damping(model, all),
                   matrix_sum(cfd_ancf::assemble_spanwise_linear_damping(model, {first}),
                              cfd_ancf::assemble_spanwise_linear_damping(model, {second})), metrics);
    require(metrics.max_abs_error <= 2.0e-14, "disjoint-region additivity failed");
    return metrics;
  });

  run(records, "H_touching_regions_equal_full_span", [] {
    const Model model = model_with_elements(4);
    const auto first = region(0.0, 4.0, {2.0, 1.0, 0.5}, {0.5, 2.0, 1.0});
    const auto second = region(4.0, 8.0, {2.0, 1.0, 0.5}, {0.5, 2.0, 1.0});
    const auto full = region(0.0, 8.0, {2.0, 1.0, 0.5}, {0.5, 2.0, 1.0});
    Metrics metrics;
    max_difference(cfd_ancf::assemble_spanwise_added_mass(model, {first, second}),
                   cfd_ancf::assemble_spanwise_added_mass(model, {full}), metrics);
    max_difference(cfd_ancf::assemble_spanwise_linear_damping(model, {first, second}),
                   cfd_ancf::assemble_spanwise_linear_damping(model, {full}), metrics);
    require(metrics.max_abs_error <= 2.0e-14, "touching regions are not equivalent to full span");
    return metrics;
  });

  run(records, "I_invalid_regions_fail_closed", [] {
    const Model model = model_with_elements(4);
    const auto valid = region(0.0, 2.0, {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0});
    std::vector<std::vector<SpanwiseHydrodynamicRegion>> invalid{
        {region(0.0, 4.8, {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0}), valid},
        {valid, region(1.5, 3.0, {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0})},
        {region(2.0, 1.0, {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0})},
        {region(-0.1, 1.0, {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0})},
        {region(0.0, 8.1, {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0})},
        {region(0.0, 1.0, {-1.0, 0.0, 0.0}, {0.0, 0.0, 0.0})},
        {region(0.0, 1.0, {0.0, 0.0, 0.0}, {0.0, -1.0, 0.0})},
        {region(std::numeric_limits<double>::quiet_NaN(), 1.0, {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0})},
        {region(0.0, std::numeric_limits<double>::infinity(), {1.0, 1.0, 1.0}, {1.0, 1.0, 1.0})}};
    for (const auto& regions : invalid) {
      bool rejected = false;
      try { (void)cfd_ancf::assemble_spanwise_added_mass(model, regions); }
      catch (const std::invalid_argument&) { rejected = true; }
      require(rejected, "invalid region was accepted");
    }
    Metrics metrics; metrics.dimension = model.ndof(); return metrics;
  });

  run(records, "J_symmetry", [] {
    const Model model = model_with_elements(4);
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(0.75, 3.1, {2.0, 1.0, 0.5}, {1.0, 3.0, 0.25}),
        region(4.2, 7.4, {0.5, 1.5, 2.5}, {4.0, 0.5, 2.0})};
    const Matrix mass = cfd_ancf::assemble_spanwise_added_mass(model, regions);
    const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, regions);
    Metrics metrics; metrics.dimension = mass.rows;
    metrics.symmetry_error = std::max(symmetry_error(mass), symmetry_error(damping));
    require(metrics.symmetry_error == 0.0, "assembler did not preserve exact symmetry");
    return metrics;
  });

  run(records, "K_positive_semidefinite_quadratic_forms", [] {
    const Model model = model_with_elements(4);
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(0.75, 3.1, {2.0, 1.0, 0.5}, {1.0, 3.0, 0.25}),
        region(4.2, 7.4, {0.5, 1.5, 2.5}, {4.0, 0.5, 2.0})};
    const Matrix mass = cfd_ancf::assemble_spanwise_added_mass(model, regions);
    const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, regions);
    Metrics metrics; metrics.dimension = mass.rows; metrics.quadratic_form_min = std::numeric_limits<double>::infinity();
    for (int seed = 0; seed < 5; ++seed) {
      const auto vector = deterministic_vector(mass.rows, seed);
      const double mass_form = quadratic(mass, vector);
      const double damping_form = quadratic(damping, vector);
      metrics.quadratic_form_min = std::min({metrics.quadratic_form_min, mass_form, damping_form});
      require(mass_form >= -roundoff_bound(mass, vector), "added-mass quadratic form is negative");
      require(damping_form >= -roundoff_bound(damping, vector), "damping quadratic form is negative");
    }
    return metrics;
  });

  run(records, "L_damping_dissipation", [] {
    const Model model = model_with_elements(4);
    const std::vector<SpanwiseHydrodynamicRegion> regions{
        region(0.5, 7.5, {0.0, 0.0, 0.0}, {1.0, 2.0, 3.0})};
    const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, regions);
    Metrics metrics; metrics.dimension = damping.rows; metrics.quadratic_form_min = std::numeric_limits<double>::infinity();
    for (int seed = 0; seed < 5; ++seed) {
      const auto velocity = deterministic_vector(damping.rows, seed + 10);
      const double power = quadratic(damping, velocity);
      metrics.quadratic_form_min = std::min(metrics.quadratic_form_min, power);
      require(power >= -roundoff_bound(damping, velocity), "damping power is negative");
    }
    return metrics;
  });

  run(records, "M_matrix_dimensions_and_finiteness", [] {
    Metrics metrics;
    for (std::size_t elements : {1u, 2u, 4u, 16u}) {
      const Model model = model_with_elements(elements);
      const std::vector<SpanwiseHydrodynamicRegion> regions{
          region(0.125, 7.875, {1.0, 2.0, 3.0}, {4.0, 5.0, 6.0})};
      const Matrix mass = cfd_ancf::assemble_spanwise_added_mass(model, regions);
      const Matrix damping = cfd_ancf::assemble_spanwise_linear_damping(model, regions);
      require(mass.rows == 6u * (elements + 1u) && mass.cols == mass.rows &&
              damping.rows == mass.rows && damping.cols == mass.cols,
              "matrix dimension is wrong");
      require(std::all_of(mass.data.begin(), mass.data.end(), [](double value) { return std::isfinite(value); }) &&
              std::all_of(damping.data.begin(), damping.data.end(), [](double value) { return std::isfinite(value); }),
              "matrix contains non-finite value");
      metrics.dimension = mass.rows;
    }
    return metrics;
  });

  emit_json(records);
  return std::all_of(records.begin(), records.end(),
                     [](const Record& record) { return record.pass; }) ? 0 : 1;
}
