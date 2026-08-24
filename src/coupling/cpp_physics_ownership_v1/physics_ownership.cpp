#include "physics_ownership.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <stdexcept>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <bcrypt.h>
#endif

namespace cfd_ancf::physics_ownership {
namespace {
using Vec3 = std::array<double, 3>;
using Vec4 = std::array<double, 4>;
constexpr double PI = 3.141592653589793238462643383279502884;

Vec4 shape(double x, double length) {
  const double xi = x / length;
  return {1.0 - 3.0 * xi * xi + 2.0 * xi * xi * xi,
          length * (xi - 2.0 * xi * xi + xi * xi * xi),
          3.0 * xi * xi - 2.0 * xi * xi * xi,
          length * (-xi * xi + xi * xi * xi)};
}

std::pair<std::vector<double>, std::vector<double>> gauss(std::size_t order) {
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
  throw std::invalid_argument("physics ownership requires Gauss order 3 or 5");
}

std::string hex_digest(const std::array<unsigned char, 32>& digest) {
  static constexpr char digits[] = "0123456789abcdef";
  std::string result;
  result.reserve(64);
  for (unsigned char value : digest) {
    result.push_back(digits[value >> 4]);
    result.push_back(digits[value & 0x0f]);
  }
  return result;
}

void add_body_component(std::vector<double>& target, const Model& model, const Vec3& line_force) {
  const auto [points, weights] = gauss(model.gauss_order);
  const double element_length = model.length_m / static_cast<double>(model.elements);
  for (std::size_t element = 0; element < model.elements; ++element) {
    for (std::size_t k = 0; k < points.size(); ++k) {
      const double x = 0.5 * (points[k] + 1.0) * element_length;
      const Vec4 s = shape(x, element_length);
      const double weight = weights[k] * element_length / 2.0;
      for (int block = 0; block < 4; ++block) {
        const std::size_t base = 6 * element + 3 * static_cast<std::size_t>(block);
        for (int component = 0; component < 3; ++component) {
          target[base + static_cast<std::size_t>(component)] +=
              weight * s[static_cast<std::size_t>(block)] * line_force[component];
        }
      }
    }
  }
}

}  // namespace

void validate_model(const Model& model) {
  const auto finite_scalar = [](double value) { return std::isfinite(value); };
  if (model.length_m <= 0.0 || model.diameter_m <= model.inner_diameter_m ||
      model.inner_diameter_m < 0.0 || model.elements < 1 || model.slices < 1 ||
      model.dt_s <= 0.0 || model.beta <= 0.0 || model.gamma <= 0.0 ||
      model.newton_tolerance <= 0.0 || model.gauss_order != 3 && model.gauss_order != 5 ||
      model.damping_alpha != 0.0 || model.damping_beta != 0.0) {
    throw std::invalid_argument("invalid physical ownership model dimensions or numerics");
  }
  for (double value : {model.length_m, model.diameter_m, model.inner_diameter_m,
                       model.top_tension_N, model.youngs_modulus_Pa,
                       model.material_density, model.fluid_density, model.gravity,
                       model.dt_s, model.beta, model.gamma, model.newton_tolerance,
                       model.damping_alpha, model.damping_beta}) {
    if (!finite_scalar(value)) throw std::invalid_argument("physical ownership model contains NaN/Inf");
  }
  if (!model.slice_positions_m.empty()) {
    if (model.slice_positions_m.size() != model.slices) {
      throw std::invalid_argument("slice position count mismatch");
    }
    for (std::size_t i = 0; i < model.slice_positions_m.size(); ++i) {
      const double position = model.slice_positions_m[i];
      if (!finite_scalar(position) || position < 0.0 || position > model.length_m ||
          (i > 0 && position < model.slice_positions_m[i - 1])) {
        throw std::invalid_argument("slice positions are not finite, bounded, or monotone");
      }
    }
  }
}

Matrix assemble_mass_matrix(const Model& model) {
  validate_model(model);
  Matrix result(model.ndof(), model.ndof());
  const auto [points, weights] = gauss(5);
  const double element_length = model.length_m / static_cast<double>(model.elements);
  const double rho_area = model.material_density * model.area();
  for (std::size_t element = 0; element < model.elements; ++element) {
    for (std::size_t k = 0; k < points.size(); ++k) {
      const double x = 0.5 * (points[k] + 1.0) * element_length;
      const Vec4 s = shape(x, element_length);
      const double weight = weights[k] * element_length / 2.0 * rho_area;
      for (int block_row = 0; block_row < 4; ++block_row) {
        for (int block_col = 0; block_col < 4; ++block_col) {
          const double value = weight * s[static_cast<std::size_t>(block_row)] *
                               s[static_cast<std::size_t>(block_col)];
          for (int component = 0; component < 3; ++component) {
            const std::size_t row = 6 * element + 3 * static_cast<std::size_t>(block_row) +
                                    static_cast<std::size_t>(component);
            const std::size_t col = 6 * element + 3 * static_cast<std::size_t>(block_col) +
                                    static_cast<std::size_t>(component);
            result(row, col) += value;
          }
        }
      }
    }
  }
  if (!std::all_of(result.data.begin(), result.data.end(),
                   [](double value) { return std::isfinite(value); })) {
    throw std::runtime_error("assembled mass matrix contains NaN/Inf");
  }
  return result;
}

BaseLoadBreakdown assemble_base_load(const Model& model) {
  validate_model(model);
  BaseLoadBreakdown result;
  const std::size_t n = model.ndof();
  result.body_gravity.assign(n, 0.0);
  result.body_buoyancy.assign(n, 0.0);
  result.top_tension.assign(n, 0.0);
  result.base.assign(n, 0.0);

  if (model.include_gravity) {
    add_body_component(result.body_gravity, model,
                       {0.0, 0.0, -model.material_density * model.area() * model.gravity});
  }
  if (model.include_buoyancy) {
    add_body_component(result.body_buoyancy, model,
                       {0.0, 0.0, model.fluid_density * model.displaced_area() * model.gravity});
  }
  const std::size_t top = 6 * model.elements;
  result.top_tension[top + 2] = model.top_tension_N;
  for (std::size_t i = 0; i < n; ++i) {
    result.base[i] = result.body_gravity[i] + result.body_buoyancy[i] + result.top_tension[i];
  }
  if (!finite(result.base)) throw std::runtime_error("assembled base load contains NaN/Inf");
  return result;
}

CfdLoadBreakdown assemble_cfd_load(const Model& model,
                                   const std::vector<double>& slice_force,
                                   ForceRepresentation representation,
                                   const std::vector<double>& slice_weights_m) {
  validate_model(model);
  if (slice_force.size() != 3 * model.slices) {
    throw std::invalid_argument("slice force dimension mismatch");
  }
  if (representation == ForceRepresentation::line_Npm && slice_weights_m.size() != model.slices) {
    throw std::invalid_argument("line_Npm requires one positive slice weight per slice");
  }
  CfdLoadBreakdown result;
  result.representation = representation;
  result.integrated_slice_force = slice_force;
  if (representation == ForceRepresentation::line_Npm) {
    for (std::size_t slice = 0; slice < model.slices; ++slice) {
      if (!std::isfinite(slice_weights_m[slice]) || slice_weights_m[slice] <= 0.0) {
        throw std::invalid_argument("slice weight must be finite and positive");
      }
      for (int component = 0; component < 3; ++component) {
        result.integrated_slice_force[3 * slice + static_cast<std::size_t>(component)] *=
            slice_weights_m[slice];
      }
    }
  }
  result.generalized_force = cfd_ancf::external_force(model, result.integrated_slice_force);
  if (!finite(result.generalized_force)) throw std::runtime_error("assembled CFD load contains NaN/Inf");
  return result;
}

std::vector<double> add_loads(const std::vector<double>& lhs, const std::vector<double>& rhs) {
  if (lhs.size() != rhs.size()) throw std::invalid_argument("load dimension mismatch");
  std::vector<double> result(lhs.size());
  for (std::size_t i = 0; i < lhs.size(); ++i) result[i] = lhs[i] + rhs[i];
  if (!finite(result)) throw std::runtime_error("combined load contains NaN/Inf");
  return result;
}

bool finite(const std::vector<double>& values) {
  return !values.empty() && std::all_of(values.begin(), values.end(),
                                        [](double value) { return std::isfinite(value); });
}

double max_abs(const std::vector<double>& values) {
  double result = 0.0;
  for (double value : values) result = std::max(result, std::abs(value));
  return result;
}

std::string sha256_vector(const std::vector<double>& values) {
#ifdef _WIN32
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  DWORD object_length = 0;
  DWORD bytes_written = 0;
  if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0) return {};
  bool ok = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                              reinterpret_cast<PUCHAR>(&object_length), sizeof(object_length),
                              &bytes_written, 0) == 0;
  std::vector<unsigned char> object(object_length);
  if (ok) ok = BCryptCreateHash(algorithm, &hash, object.data(), object_length, nullptr, 0, 0) == 0;
  if (ok && !values.empty()) {
    ok = BCryptHashData(hash, reinterpret_cast<PUCHAR>(const_cast<double*>(values.data())),
                        static_cast<ULONG>(values.size() * sizeof(double)), 0) == 0;
  }
  std::array<unsigned char, 32> digest{};
  if (ok) ok = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) == 0;
  if (hash != nullptr) BCryptDestroyHash(hash);
  if (algorithm != nullptr) BCryptCloseAlgorithmProvider(algorithm, 0);
  return ok ? hex_digest(digest) : std::string{};
#else
  (void)values;
  return {};
#endif
}

const char* representation_name(ForceRepresentation representation) {
  return representation == ForceRepresentation::integrated_N ? "integrated_N" : "line_Npm";
}

}  // namespace cfd_ancf::physics_ownership
