#pragma once

#include <cstddef>
#include <array>
#include <limits>
#include <string>
#include <utility>
#include <vector>

namespace cfd_ancf {

// Dense ANCF matrices are intentionally bounded at the IPC boundary.  This
// protects the worker from malformed frames that could otherwise request an
// unbounded n-by-n allocation before numerical validation runs.
constexpr std::size_t MAX_NDOF = 2048;
// The v1 wire contract is a bounded transient solver.  A larger value can
// turn a malformed frame into an unbounded CPU request before fail-closed
// cleanup runs.
constexpr std::size_t MAX_NEWTON = 1000;

struct Matrix {
  std::size_t rows = 0, cols = 0;
  std::vector<double> data;
  Matrix() = default;
  Matrix(std::size_t r, std::size_t c, double value = 0.0) : rows(r), cols(c), data(r * c, value) {}
  double& operator()(std::size_t r, std::size_t c) { return data[r * cols + c]; }
  double operator()(std::size_t r, std::size_t c) const { return data[r * cols + c]; }
};

struct Model {
  double length_m = 10.0;
  double diameter_m = 1.0;
  double inner_diameter_m = 0.9;
  std::size_t elements = 2;
  std::size_t slices = 3;
  std::vector<double> slice_positions_m;
  double top_tension_N = 1.0e7;
  double youngs_modulus_Pa = 2.07e11;
  double material_density = 7850.0;
  double fluid_density = 1025.0;
  double gravity = 9.81;
  bool include_gravity = true;
  bool include_buoyancy = true;
  double dt_s = 0.00125;
  double beta = 0.25;
  double gamma = 0.5;
  std::size_t max_newton = 40;
  double newton_tolerance = 1.0e-8;
  double damping_alpha = 0.0;
  double damping_beta = 0.0;
  std::size_t gauss_order = 3;
  // The mass quadrature is an independent part of the MATLAB contract.
  std::size_t mass_gauss_order = 5;
  // Empty vectors select the v1 canonical boundary contract.  Wire requests
  // and checkpoints should populate them explicitly.
  std::vector<std::size_t> fixed_dof;
  std::vector<double> prescribed_values;
  std::string boundary_contract_id = "ancf_v1_bottom_top_xy_zero";
  double area() const;
  double displaced_area() const;
  double EA() const;
  double EI() const;
  std::size_t ndof() const {
    constexpr std::size_t max_value = (std::numeric_limits<std::size_t>::max)();
    if (elements == max_value || elements > (max_value - 1u) / 6u) return max_value;
    return 6u * (elements + 1u);
  }
};

struct State {
  std::vector<double> q, qdot, qddot, base_load;
  Matrix mass, damping;
  double time_s = 0.0;
  std::size_t step = 0;
  double residual = 0.0;
  std::size_t iterations = 0;
};

struct StepDiagnostics {
  double initial_residual = 0.0;
  double residual = 0.0;
  std::size_t iterations = 0;
  bool converged = false;
  // Profiling-only timings. They are not part of the numerical contract.
  double matrix_assembly_s = 0.0;
  double linear_solve_s = 0.0;
  double state_update_s = 0.0;
  double predictor_s = 0.0;
  double external_mapping_s = 0.0;
  // MATLAB's free-DOF residual scale, retained for audit diagnostics.
  double residual_scale = 0.0;
};

// Offline-only Newton trace. The default production advance path does not
// allocate or populate this record; diagnostics may pass a vector to capture
// the exact production residual/tangent path for MATLAB comparison.
struct NewtonIterationTrace {
  std::size_t iteration = 0;
  std::vector<double> q;
  std::vector<double> qdot;
  std::vector<double> qddot;
  std::vector<double> internal_force;
  std::vector<double> residual;
  Matrix tangent;
  std::vector<double> increment;
  double residual_norm = 0.0;
  bool converged = false;
};

// Offline-only trace for MATLAB/C++ forensic comparison.  This is deliberately
// separate from the wire response so diagnostics cannot alter production IPC.
struct ForensicPoint {
  std::size_t element = 0;
  std::size_t gauss_index = 0;
  double xi = 0.0;
  double x = 0.0;
  std::array<double, 3> a{};
  std::array<double, 3> b{};
  std::array<double, 3> v{};
  double a2 = 0.0;
  double v2 = 0.0;
  double eps = 0.0;
  std::array<double, 3> ga_b{};
  std::array<double, 3> gb_b{};
  std::array<double, 3> ga{};
  std::array<double, 3> gb{};
  std::array<double, 12> bga{};
  std::array<double, 12> cgb{};
  std::array<double, 12> contribution{};
  std::array<double, 144> tangent_contribution{};
};

struct ForensicResult {
  std::vector<ForensicPoint> points;
  std::vector<double> force;
  Matrix tangent;
};

// Production assembly may optionally emit this trace.  The callback is
// intentionally data-only: enabling it cannot select a second formula or
// change the arithmetic used by the solver.
struct AssemblyTrace {
  std::vector<ForensicPoint> points;
};

State make_reference_state(const Model& model);
void validate_model(const Model& model);
void symmetrize_mass(State& state);
StepDiagnostics advance(State& state, const Model& model, const std::vector<double>& slice_force,
                        std::vector<NewtonIterationTrace>* trace = nullptr);
void internal_force_tangent(const std::vector<double>& q, const Model& model, std::vector<double>& force, Matrix& tangent);
void internal_force_tangent(const std::vector<double>& q, const Model& model, std::vector<double>& force,
                            Matrix& tangent, AssemblyTrace* trace);
ForensicResult internal_force_forensic(const std::vector<double>& q, const Model& model);
std::vector<double> external_force(const Model& model, const std::vector<double>& slice_force);
Matrix mapping_H3(const Model& model);
bool finite(const State& state);

}  // namespace cfd_ancf
