#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr double kPi = 3.141592653589793238462643383279502884;

double dot(const std::vector<double>& left, const std::vector<double>& right) {
  if (left.size() != right.size()) throw std::invalid_argument("dot dimensions");
  double value = 0.0;
  for (std::size_t index = 0; index < left.size(); ++index) value += left[index] * right[index];
  return value;
}

std::vector<double> multiply(const cfd_ancf::Matrix& matrix, const std::vector<double>& vector) {
  if (matrix.cols != vector.size()) throw std::invalid_argument("matrix/vector dimensions");
  std::vector<double> result(matrix.rows, 0.0);
  for (std::size_t row = 0; row < matrix.rows; ++row)
    for (std::size_t col = 0; col < matrix.cols; ++col) result[row] += matrix(row, col) * vector[col];
  return result;
}

cfd_ancf::Matrix transpose(const cfd_ancf::Matrix& matrix) {
  cfd_ancf::Matrix result(matrix.cols, matrix.rows);
  for (std::size_t row = 0; row < matrix.rows; ++row)
    for (std::size_t col = 0; col < matrix.cols; ++col) result(col, row) = matrix(row, col);
  return result;
}

cfd_ancf::Matrix multiply(const cfd_ancf::Matrix& left, const cfd_ancf::Matrix& right) {
  if (left.cols != right.rows) throw std::invalid_argument("matrix dimensions");
  cfd_ancf::Matrix result(left.rows, right.cols);
  for (std::size_t row = 0; row < left.rows; ++row)
    for (std::size_t mid = 0; mid < left.cols; ++mid)
      for (std::size_t col = 0; col < right.cols; ++col) result(row, col) += left(row, mid) * right(mid, col);
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
        if (!std::isfinite(value) || value <= 0.0) throw std::runtime_error("mass matrix is not positive definite");
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

struct EigenSystem {
  std::vector<double> values;
  cfd_ancf::Matrix vectors;
};

EigenSystem jacobi_symmetric(cfd_ancf::Matrix matrix) {
  if (matrix.rows != matrix.cols) throw std::invalid_argument("eigen matrix is not square");
  const std::size_t n = matrix.rows;
  cfd_ancf::Matrix vectors(n, n);
  for (std::size_t index = 0; index < n; ++index) vectors(index, index) = 1.0;
  const double scale = [&]() {
    double value = 1.0;
    for (double item : matrix.data) value = std::max(value, std::abs(item));
    return value;
  }();
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
        for (std::size_t row = 0; row < n; ++row) result.vectors(row, column) = vectors(row, order[column]);
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

cfd_ancf::Matrix select(const cfd_ancf::Matrix& source, const std::vector<std::size_t>& dof) {
  cfd_ancf::Matrix result(dof.size(), dof.size());
  for (std::size_t row = 0; row < dof.size(); ++row)
    for (std::size_t col = 0; col < dof.size(); ++col) result(row, col) = source(dof[row], dof[col]);
  return result;
}

std::vector<std::size_t> transverse_y_dof(const cfd_ancf::Model& model) {
  std::vector<std::size_t> dof;
  for (std::size_t node = 0; node <= model.elements; ++node) {
    if (node != 0 && node != model.elements) dof.push_back(6u * node + 1u);
    dof.push_back(6u * node + 4u);
  }
  return dof;
}

double internal_energy(const cfd_ancf::State& state, const cfd_ancf::Model& model) {
  const double length = model.length_m / static_cast<double>(model.elements);
  const double xi[3] = {-std::sqrt(3.0 / 5.0), 0.0, std::sqrt(3.0 / 5.0)};
  const double weight[3] = {5.0 / 9.0, 8.0 / 9.0, 5.0 / 9.0};
  double energy = 0.0;
  for (std::size_t element = 0; element < model.elements; ++element) {
    const std::size_t base = 6u * element;
    for (std::size_t point = 0; point < 3; ++point) {
      const double local_x = 0.5 * (xi[point] + 1.0) * length;
      const double r = local_x / length;
      const double s1[4] = {(6.0 * r * r - 6.0 * r) / length, 1.0 - 4.0 * r + 3.0 * r * r,
                            (-6.0 * r * r + 6.0 * r) / length, -2.0 * r + 3.0 * r * r};
      const double s2[4] = {(12.0 * r - 6.0) / (length * length), (-4.0 + 6.0 * r) / length,
                            (6.0 - 12.0 * r) / (length * length), (-2.0 + 6.0 * r) / length};
      double a[3] = {0.0, 0.0, 0.0};
      double b[3] = {0.0, 0.0, 0.0};
      for (std::size_t node = 0; node < 4; ++node)
        for (std::size_t component = 0; component < 3; ++component) {
          a[component] += s1[node] * state.q[base + 3u * node + component];
          b[component] += s2[node] * state.q[base + 3u * node + component];
        }
      const double a2 = a[0] * a[0] + a[1] * a[1] + a[2] * a[2];
      const double cross[3] = {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
      const double bending = cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2];
      const double strain = 0.5 * (a2 - 1.0);
      energy += (0.5 * model.EA() * strain * strain + 0.5 * model.EI() * bending / std::pow(a2, 3.0)) * weight[point] * length / 2.0;
    }
  }
  return energy;
}

double kinetic_energy(const cfd_ancf::State& state) { return 0.5 * dot(state.qdot, multiply(state.mass, state.qdot)); }

double potential_energy(const cfd_ancf::State& state, const cfd_ancf::Model& model) {
  return internal_energy(state, model) - dot(state.base_load, state.q);
}

void read_model(cfd_ancf::Model& model, double& duration_s, double& perturbation_m, std::size_t& output_every) {
  std::size_t elements = 0, slices = 0, gauss = 0, mass_gauss = 0, max_newton = 0;
  if (!(std::cin >> model.length_m >> model.diameter_m >> model.inner_diameter_m >> elements >> slices >> model.top_tension_N >>
        model.youngs_modulus_Pa >> model.material_density >> model.fluid_density >> model.gravity >> model.dt_s >> model.beta >>
        model.gamma >> model.newton_tolerance >> gauss >> mass_gauss >> max_newton >> duration_s >> perturbation_m >> output_every)) {
    throw std::runtime_error("expected modal/free diagnostic input header");
  }
  model.elements = elements;
  model.slices = slices;
  model.gauss_order = gauss;
  model.mass_gauss_order = mass_gauss;
  model.max_newton = max_newton;
  model.slice_positions_m.resize(slices);
  for (double& position : model.slice_positions_m) if (!(std::cin >> position)) throw std::runtime_error("missing slice position");
  if (!std::isfinite(duration_s) || duration_s <= 0.0 || !std::isfinite(perturbation_m) || perturbation_m <= 0.0 || output_every == 0)
    throw std::runtime_error("invalid free-vibration contract");
  cfd_ancf::validate_model(model);
}

}  // namespace

int main() {
  try {
    cfd_ancf::Model model;
    double duration_s = 0.0, perturbation_m = 0.0;
    std::size_t output_every = 0;
    read_model(model, duration_s, perturbation_m, output_every);
    auto state = cfd_ancf::make_reference_state(model);
    const auto base_load = cfd_ancf::static_base_load(model);
    const auto equilibrium = cfd_ancf::static_equilibrium(state, model, base_load, 40, 0.8);
    std::vector<double> internal;
    cfd_ancf::Matrix stiffness_full;
    cfd_ancf::internal_force_tangent(state.q, model, internal, stiffness_full);
    const auto free_y = transverse_y_dof(model);
    const auto stiffness = select(stiffness_full, free_y);
    const auto mass = select(state.mass, free_y);
    const auto lower = cholesky_lower(mass);
    const auto inverse = inverse_lower(lower);
    const auto transformed = multiply(multiply(inverse, stiffness), transpose(inverse));
    const auto eigen = jacobi_symmetric(transformed);
    std::vector<std::vector<double>> modes;
    std::vector<double> values;
    for (std::size_t column = 0; column < eigen.values.size() && modes.size() < 6; ++column) {
      const double value = eigen.values[column];
      if (!std::isfinite(value) || value <= 1.0e-12) continue;
      std::vector<double> vector(eigen.vectors.rows);
      for (std::size_t row = 0; row < eigen.vectors.rows; ++row) vector[row] = eigen.vectors(row, column);
      vector = multiply(transpose(inverse), vector);
      const double norm = std::sqrt(dot(vector, multiply(mass, vector)));
      for (double& item : vector) item /= norm;
      modes.push_back(std::move(vector));
      values.push_back(value);
    }
    if (modes.size() != 6) throw std::runtime_error("fewer than six positive transverse modes");
    std::cout << std::setprecision(17);
    std::cout << "meta equilibrium_residual " << equilibrium.residual << " equilibrium_iterations " << equilibrium.iterations
              << " transverse_free_dof " << free_y.size() << " damping_alpha " << model.damping_alpha
              << " damping_beta " << model.damping_beta << '\n';
    for (std::size_t mode = 0; mode < modes.size(); ++mode) {
      const auto residual = [&]() {
        const auto left = multiply(stiffness, modes[mode]);
        const auto right = multiply(mass, modes[mode]);
        double numerator = 0.0, denominator = 0.0;
        for (std::size_t index = 0; index < left.size(); ++index) {
          numerator += std::pow(left[index] - values[mode] * right[index], 2.0);
          denominator += std::pow(left[index], 2.0) + std::pow(values[mode] * right[index], 2.0);
        }
        return std::sqrt(numerator) / std::max(std::sqrt(denominator), std::numeric_limits<double>::min());
      }();
      double maximum = 0.0;
      for (std::size_t node = 1; node < model.elements; ++node) maximum = std::max(maximum, std::abs(modes[mode][2u * node - 1u]));
      std::cout << "mode " << (mode + 1u) << " lambda_rad2ps2 " << values[mode] << " frequency_hz "
                << std::sqrt(values[mode]) / (2.0 * kPi) << " mass_norm " << dot(modes[mode], multiply(mass, modes[mode]))
                << " residual " << residual << " max_nodal_y_per_mass_norm " << maximum << '\n';
      std::cout << "shape " << (mode + 1u);
      for (std::size_t node = 0; node <= model.elements; ++node) {
        const double value = node == 0 || node == model.elements ? 0.0 : modes[mode][2u * node - 1u] / maximum;
        std::cout << ' ' << value;
      }
      std::cout << '\n';
    }
    const double equilibrium_total = kinetic_energy(state) + potential_energy(state, model);
    const auto equilibrium_q = state.q;
    double maximum = 0.0;
    for (std::size_t node = 1; node < model.elements; ++node) maximum = std::max(maximum, std::abs(modes.front()[2u * node - 1u]));
    for (std::size_t index = 0; index < modes.front().size(); ++index) state.q[free_y[index]] += modes.front()[index] * perturbation_m / maximum;
    const double initial_total = kinetic_energy(state) + potential_energy(state, model);
    const std::vector<double> zero_force(3u * model.slices, 0.0);
    const std::size_t steps = static_cast<std::size_t>(std::llround(duration_s / model.dt_s));
    if (steps < 4u || std::abs(static_cast<double>(steps) * model.dt_s - duration_s) > 1.0e-12)
      throw std::runtime_error("duration must be an integral number of time steps and contain at least four steps");
    for (std::size_t step = 0; step <= steps; ++step) {
      if (step % output_every == 0u || step == steps) {
        const double kinetic = kinetic_energy(state);
        const double strain_energy = internal_energy(state, model);
        const double potential = potential_energy(state, model);
        std::vector<double> transverse_displacement(free_y.size());
        for (std::size_t index = 0; index < free_y.size(); ++index)
          transverse_displacement[index] = state.q[free_y[index]] - equilibrium_q[free_y[index]];
        const double modal_coordinate_1 = dot(modes.front(), multiply(mass, transverse_displacement));
        std::cout << "sample time_s " << state.time_s << " kinetic_J " << kinetic
                  << " strain_energy_J " << strain_energy << " potential_J "
                  << potential << " total_J " << kinetic + potential
                  << " incremental_total_J " << kinetic + potential - equilibrium_total
                  << " modal_coordinate_1 " << modal_coordinate_1;
        for (std::size_t slice = 0; slice < model.slice_positions_m.size(); ++slice) {
          const double position = model.slice_positions_m[slice];
          const std::size_t element = std::min(model.elements - 1u, static_cast<std::size_t>(std::floor(position / (model.length_m / model.elements))));
          const double local = position - static_cast<double>(element) * model.length_m / model.elements;
          const double r = local / (model.length_m / model.elements);
          const double shape[4] = {1.0 - 3.0 * r * r + 2.0 * r * r * r,
                                   (model.length_m / model.elements) * (r - 2.0 * r * r + r * r * r),
                                   3.0 * r * r - 2.0 * r * r * r,
                                   (model.length_m / model.elements) * (-r * r + r * r * r)};
          const std::size_t base = 6u * element;
          const double y = shape[0] * state.q[base + 1u] + shape[1] * state.q[base + 4u] + shape[2] * state.q[base + 7u] + shape[3] * state.q[base + 10u];
          const double vy = shape[0] * state.qdot[base + 1u] + shape[1] * state.qdot[base + 4u] + shape[2] * state.qdot[base + 7u] + shape[3] * state.qdot[base + 10u];
          std::cout << " y_" << (slice + 1u) << ' ' << y << " vy_" << (slice + 1u) << ' ' << vy;
        }
        std::cout << '\n';
      }
      if (step != steps) (void)cfd_ancf::advance(state, model, zero_force);
    }
    const double final_total = kinetic_energy(state) + potential_energy(state, model);
    const double initial_incremental = initial_total - equilibrium_total;
    const double final_incremental = final_total - equilibrium_total;
    std::cout << "summary initial_total_J " << initial_total << " final_total_J " << final_total
              << " initial_incremental_total_J " << initial_incremental << " final_incremental_total_J " << final_incremental
              << " relative_incremental_energy_change " << std::abs(final_incremental - initial_incremental) /
                  std::max(std::abs(initial_incremental), 1.0e-30)
              << " zero_fluid_force true" << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ancf_modal_free_diagnostic_error=" << error.what() << '\n';
    return 2;
  }
}
