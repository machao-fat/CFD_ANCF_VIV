// Offline MATLAB/C++ ANCF comparison diagnostic.  It deliberately has no
// IPC, CFD, preCICE, checkpoint, or historical-evidence dependency.
#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <vector>

namespace {
constexpr double PI = 3.141592653589793238462643383279502884;

double dot(const std::vector<double>& a, const std::vector<double>& b) {
  if (a.size() != b.size()) throw std::invalid_argument("dot dimensions");
  double value = 0.0;
  for (std::size_t i = 0; i < a.size(); ++i) value += a[i] * b[i];
  return value;
}

cfd_ancf::Matrix transpose(const cfd_ancf::Matrix& a) {
  cfd_ancf::Matrix result(a.cols, a.rows);
  for (std::size_t i = 0; i < a.rows; ++i)
    for (std::size_t j = 0; j < a.cols; ++j) result(j, i) = a(i, j);
  return result;
}

cfd_ancf::Matrix multiply(const cfd_ancf::Matrix& a, const cfd_ancf::Matrix& b) {
  if (a.cols != b.rows) throw std::invalid_argument("matrix dimensions");
  cfd_ancf::Matrix result(a.rows, b.cols);
  for (std::size_t i = 0; i < a.rows; ++i)
    for (std::size_t k = 0; k < a.cols; ++k)
      for (std::size_t j = 0; j < b.cols; ++j) result(i, j) += a(i, k) * b(k, j);
  return result;
}

std::vector<double> multiply(const cfd_ancf::Matrix& a, const std::vector<double>& b) {
  if (a.cols != b.size()) throw std::invalid_argument("matrix/vector dimensions");
  std::vector<double> result(a.rows, 0.0);
  for (std::size_t i = 0; i < a.rows; ++i)
    for (std::size_t j = 0; j < a.cols; ++j) result[i] += a(i, j) * b[j];
  return result;
}

cfd_ancf::Matrix select(const cfd_ancf::Matrix& source, const std::vector<std::size_t>& dof) {
  cfd_ancf::Matrix result(dof.size(), dof.size());
  for (std::size_t i = 0; i < dof.size(); ++i)
    for (std::size_t j = 0; j < dof.size(); ++j) result(i, j) = source(dof[i], dof[j]);
  return result;
}

cfd_ancf::Matrix cholesky_lower(const cfd_ancf::Matrix& matrix) {
  cfd_ancf::Matrix result(matrix.rows, matrix.cols);
  for (std::size_t i = 0; i < matrix.rows; ++i) {
    for (std::size_t j = 0; j <= i; ++j) {
      double value = matrix(i, j);
      for (std::size_t k = 0; k < j; ++k) value -= result(i, k) * result(j, k);
      if (i == j) {
        if (!std::isfinite(value) || value <= 0.0) throw std::runtime_error("mass is not positive definite");
        result(i, j) = std::sqrt(value);
      } else {
        result(i, j) = value / result(j, j);
      }
    }
  }
  return result;
}

cfd_ancf::Matrix inverse_lower(const cfd_ancf::Matrix& lower) {
  cfd_ancf::Matrix result(lower.rows, lower.cols);
  for (std::size_t col = 0; col < lower.cols; ++col) {
    for (std::size_t row = 0; row < lower.rows; ++row) {
      double value = row == col ? 1.0 : 0.0;
      for (std::size_t k = 0; k < row; ++k) value -= lower(row, k) * result(k, col);
      result(row, col) = value / lower(row, row);
    }
  }
  return result;
}

struct EigenSystem { std::vector<double> values; cfd_ancf::Matrix vectors; };

EigenSystem jacobi_symmetric(cfd_ancf::Matrix matrix) {
  const std::size_t n = matrix.rows;
  cfd_ancf::Matrix vectors(n, n);
  for (std::size_t i = 0; i < n; ++i) vectors(i, i) = 1.0;
  double scale = 1.0;
  for (double value : matrix.data) scale = std::max(scale, std::abs(value));
  for (std::size_t iteration = 0; iteration < 100u * n * n; ++iteration) {
    std::size_t p = 0, q = 1; double maximum = 0.0;
    for (std::size_t row = 0; row < n; ++row) for (std::size_t col = row + 1; col < n; ++col)
      if (std::abs(matrix(row, col)) > maximum) { maximum = std::abs(matrix(row, col)); p = row; q = col; }
    if (maximum <= 1.0e-12 * scale) {
      std::vector<std::size_t> order(n); std::iota(order.begin(), order.end(), 0u);
      std::sort(order.begin(), order.end(), [&matrix](std::size_t a, std::size_t b) { return matrix(a, a) < matrix(b, b); });
      EigenSystem result; result.values.resize(n); result.vectors = cfd_ancf::Matrix(n, n);
      for (std::size_t col = 0; col < n; ++col) {
        result.values[col] = matrix(order[col], order[col]);
        for (std::size_t row = 0; row < n; ++row) result.vectors(row, col) = vectors(row, order[col]);
      }
      return result;
    }
    const double app = matrix(p, p), aqq = matrix(q, q), apq = matrix(p, q);
    const double angle = 0.5 * std::atan2(2.0 * apq, aqq - app);
    const double c = std::cos(angle), s = std::sin(angle);
    for (std::size_t i = 0; i < n; ++i) {
      if (i == p || i == q) continue;
      const double aip = matrix(i, p), aiq = matrix(i, q);
      matrix(i, p) = matrix(p, i) = c * aip - s * aiq;
      matrix(i, q) = matrix(q, i) = s * aip + c * aiq;
    }
    matrix(p, p) = c*c*app - 2*c*s*apq + s*s*aqq;
    matrix(q, q) = s*s*app + 2*s*c*apq + c*c*aqq;
    matrix(p, q) = matrix(q, p) = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
      const double vip = vectors(i, p), viq = vectors(i, q);
      vectors(i, p) = c * vip - s * viq; vectors(i, q) = s * vip + c * viq;
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

std::array<double, 4> shape(double x, double length) {
  const double r = x / length;
  return {1.0 - 3.0*r*r + 2.0*r*r*r, length*(r - 2.0*r*r + r*r*r),
          3.0*r*r - 2.0*r*r*r, length*(-r*r + r*r*r)};
}

std::array<double, 3> position(const cfd_ancf::State& state, const cfd_ancf::Model& model, double s) {
  const double length = model.length_m / model.elements;
  const std::size_t element = s == model.length_m ? model.elements - 1u :
      std::min(model.elements - 1u, static_cast<std::size_t>(std::floor(s / length)));
  const auto N = shape(s - element * length, length); const std::size_t base = 6u * element;
  std::array<double, 3> out{};
  for (std::size_t node = 0; node < 4; ++node) for (std::size_t c = 0; c < 3; ++c) out[c] += N[node] * state.q[base + 3u*node + c];
  return out;
}

std::array<double, 2> y_and_vy(const cfd_ancf::State& state, const cfd_ancf::Model& model, double s) {
  const double length = model.length_m / model.elements;
  const std::size_t element = s == model.length_m ? model.elements - 1u :
      std::min(model.elements - 1u, static_cast<std::size_t>(std::floor(s / length)));
  const auto N = shape(s - element * length, length); const std::size_t base = 6u * element;
  double y = 0.0, vy = 0.0;
  for (std::size_t node = 0; node < 4; ++node) { y += N[node] * state.q[base + 3u*node + 1u]; vy += N[node] * state.qdot[base + 3u*node + 1u]; }
  return {y, vy};
}

double internal_energy(const cfd_ancf::State& state, const cfd_ancf::Model& model) {
  const double length = model.length_m / model.elements;
  const double xi[3] = {-std::sqrt(3.0/5.0), 0.0, std::sqrt(3.0/5.0)};
  const double weight[3] = {5.0/9.0, 8.0/9.0, 5.0/9.0}; double energy = 0.0;
  for (std::size_t e = 0; e < model.elements; ++e) for (std::size_t k = 0; k < 3; ++k) {
    const double r = 0.5 * (xi[k] + 1.0);
    const double s1[4] = {(6*r*r-6*r)/length, 1-4*r+3*r*r, (-6*r*r+6*r)/length, -2*r+3*r*r};
    const double s2[4] = {(12*r-6)/(length*length), (-4+6*r)/length, (6-12*r)/(length*length), (-2+6*r)/length};
    double a[3] = {}, b[3] = {}; const std::size_t base = 6u * e;
    for (std::size_t node = 0; node < 4; ++node) for (std::size_t c = 0; c < 3; ++c) { a[c] += s1[node]*state.q[base+3u*node+c]; b[c] += s2[node]*state.q[base+3u*node+c]; }
    const double a2 = a[0]*a[0]+a[1]*a[1]+a[2]*a[2];
    const double cross[3] = {a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]};
    const double bending = cross[0]*cross[0]+cross[1]*cross[1]+cross[2]*cross[2]; const double strain = 0.5*(a2-1.0);
    energy += (0.5*model.EA()*strain*strain + 0.5*model.EI()*bending/std::pow(a2,3.0))*weight[k]*length/2.0;
  }
  return energy;
}

double kinetic_energy(const cfd_ancf::State& state) { return 0.5 * dot(state.qdot, multiply(state.mass, state.qdot)); }

void read_model(cfd_ancf::Model& model, double& duration, std::size_t& output_every, double& amplitude) {
  std::size_t elements = 0, slices = 0, gauss = 0, max_newton = 0;
  if (!(std::cin >> model.length_m >> model.diameter_m >> model.inner_diameter_m >> elements >> slices >> model.top_tension_N >>
        model.youngs_modulus_Pa >> model.material_density >> model.fluid_density >> model.gravity >> model.dt_s >> model.beta >> model.gamma >>
        model.newton_tolerance >> gauss >> max_newton >> duration >> output_every >> amplitude)) throw std::runtime_error("invalid input header");
  model.elements = elements; model.slices = slices; model.gauss_order = gauss; model.mass_gauss_order = 5; model.max_newton = max_newton;
  model.slice_positions_m.resize(slices); for (double& value : model.slice_positions_m) if (!(std::cin >> value)) throw std::runtime_error("missing slice position");
  if (duration < 50.0 || output_every == 0 || amplitude <= 0.0 || !std::isfinite(duration) || !std::isfinite(amplitude)) throw std::runtime_error("invalid frozen dynamic contract");
  cfd_ancf::validate_model(model);
}
}  // namespace

int main() {
  try {
    cfd_ancf::Model model; double duration = 0.0, amplitude = 0.0; std::size_t output_every = 0;
    read_model(model, duration, output_every, amplitude);
    auto state = cfd_ancf::make_reference_state(model); const auto base = cfd_ancf::static_base_load(model);
    const auto static_diag = cfd_ancf::static_equilibrium(state, model, base, 40, 0.8);
    std::vector<double> internal; cfd_ancf::Matrix tangent; cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
    const auto free_y = free_y_dof(model); const auto mass = select(state.mass, free_y); const auto stiffness = select(tangent, free_y);
    const auto lower = cholesky_lower(mass); const auto inverse = inverse_lower(lower); const auto eig = jacobi_symmetric(multiply(multiply(inverse, stiffness), transpose(inverse)));
    std::vector<std::vector<double>> modes; std::vector<double> values;
    for (std::size_t col = 0; col < eig.values.size() && modes.size() < 6; ++col) if (eig.values[col] > 1.0e-12 && std::isfinite(eig.values[col])) {
      std::vector<double> mode(eig.vectors.rows); for (std::size_t row = 0; row < mode.size(); ++row) mode[row] = eig.vectors(row, col);
      mode = multiply(transpose(inverse), mode); const double norm = std::sqrt(dot(mode, multiply(mass, mode))); for (double& value : mode) value /= norm;
      modes.push_back(std::move(mode)); values.push_back(eig.values[col]);
    }
    if (modes.size() != 6) throw std::runtime_error("fewer than six modes");
    std::cout << std::setprecision(17);
    std::cout << "meta static_residual " << static_diag.residual << " static_iterations " << static_diag.iterations << " duration_s " << duration << " dt_s " << model.dt_s << " amplitude_m " << amplitude << '\n';
    std::cout << "core_vector internal_force " << internal.size();
    for (double value : internal) std::cout << ' ' << value;
    std::cout << '\n';
    std::cout << "core_matrix mass " << state.mass.rows << ' ' << state.mass.cols;
    for (double value : state.mass.data) std::cout << ' ' << value;
    std::cout << '\n';
    std::cout << "core_matrix tangent " << tangent.rows << ' ' << tangent.cols;
    for (double value : tangent.data) std::cout << ' ' << value;
    std::cout << '\n';
    for (std::size_t i = 0; i <= 2u*model.elements; ++i) { const double s = 0.5 * model.length_m * static_cast<double>(i) / model.elements; const auto r = position(state, model, s); std::cout << "static_sample s_m " << s << " x_m " << r[0] << " y_m " << r[1] << " z_m " << r[2] << '\n'; }
    for (std::size_t k = 0; k < modes.size(); ++k) {
      const auto left = multiply(stiffness, modes[k]); const auto right = multiply(mass, modes[k]); double numerator = 0.0, denominator = 0.0;
      for (std::size_t i = 0; i < left.size(); ++i) { numerator += std::pow(left[i]-values[k]*right[i],2.0); denominator += std::pow(left[i],2.0)+std::pow(values[k]*right[i],2.0); }
      std::cout << "mode index " << (k+1u) << " frequency_hz " << std::sqrt(values[k])/(2.0*PI) << " mass_norm " << dot(modes[k],multiply(mass,modes[k])) << " residual " << std::sqrt(numerator)/std::max(std::sqrt(denominator),std::numeric_limits<double>::min()) << '\n';
      double maximum = 0.0; for (std::size_t node = 1; node < model.elements; ++node) maximum = std::max(maximum,std::abs(modes[k][2u*node-1u]));
      std::cout << "mode_shape index " << (k+1u); for (std::size_t node = 0; node <= model.elements; ++node) { const double value = (node == 0 || node == model.elements) ? 0.0 : modes[k][2u*node-1u]/maximum; std::cout << " value_" << node << ' ' << value; } std::cout << '\n';
    }
    const auto equilibrium = state.q; for (std::size_t node = 0; node <= model.elements; ++node) { const double s = model.length_m*node/model.elements; state.q[6u*node+1u] += amplitude*std::sin(PI*s/model.length_m); state.q[6u*node+4u] += amplitude*PI/model.length_m*std::cos(PI*s/model.length_m); }
    const double equilibrium_energy = internal_energy(cfd_ancf::State{equilibrium, {}, {}, state.base_load, state.mass, state.damping}, model) - dot(state.base_load,equilibrium);
    const std::size_t steps = static_cast<std::size_t>(std::llround(duration/model.dt_s)); if (std::abs(steps*model.dt_s-duration) > 1.0e-12) throw std::runtime_error("duration/dt mismatch");
    const std::vector<double> zero_force(3u*model.slices,0.0);
    for (std::size_t step = 0; step <= steps; ++step) {
      if (step % output_every == 0 || step == steps) { const double strain = internal_energy(state,model); const double kinetic = kinetic_energy(state); std::cout << "dynamic_sample time_s " << state.time_s << " kinetic_J " << kinetic << " strain_energy_J " << strain << " incremental_energy_J " << strain+kinetic-dot(state.base_load,state.q)-equilibrium_energy; for (std::size_t slice = 0; slice < model.slices; ++slice) { const auto v=y_and_vy(state,model,model.slice_positions_m[slice]); std::cout << " y_" << slice << ' ' << v[0] << " vy_" << slice << ' ' << v[1]; } std::cout << '\n'; }
      if (step != steps) (void)cfd_ancf::advance(state,model,zero_force);
    }
    return 0;
  } catch (const std::exception& error) { std::cerr << "baseline_cross_diagnostic_error=" << error.what() << '\n'; return 2; }
}
