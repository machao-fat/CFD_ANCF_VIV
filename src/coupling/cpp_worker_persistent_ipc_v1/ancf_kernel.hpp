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

enum class SectionPropertyMode {
  LegacyPhysicalSection,
  ExplicitSectionProperties
};

// The legacy mode is the protected H^T F point-lumped contract.  Distributed
// modes use a separate typed input and never reinterpret the legacy force
// vector as a line load.
enum class SpanwiseLoadReconstruction {
  LegacyPointLumped,
  PiecewiseLinearDistributed
};

enum class SpanwiseEndpointPolicy {
  NearestConstant
};

struct SpanwiseLoadSample {
  double s_m = 0.0;
  std::array<double, 3> line_force_Npm{};
};

struct SpanwiseLoadRegion {
  double s_min_m = 0.0;
  double s_max_m = 0.0;
};

struct SpanwiseLoadInput {
  // Fail closed to the historical mapping when a caller does not opt into
  // the new typed distributed-load contract explicitly.
  SpanwiseLoadReconstruction mode = SpanwiseLoadReconstruction::LegacyPointLumped;
  SpanwiseEndpointPolicy endpoint_policy = SpanwiseEndpointPolicy::NearestConstant;
  SpanwiseLoadRegion active_region;
  std::vector<SpanwiseLoadSample> samples;
};

struct Matrix {
  std::size_t rows = 0, cols = 0;
  std::vector<double> data;
  Matrix() = default;
  Matrix(std::size_t r, std::size_t c, double value = 0.0) : rows(r), cols(c), data(r * c, value) {}
  double& operator()(std::size_t r, std::size_t c) { return data[r * cols + c]; }
  double operator()(std::size_t r, std::size_t c) const { return data[r * cols + c]; }
};

// A data-only, reference-coordinate interval.  Its resolved coefficients are
// deliberately global ANCF x/y/z values; deriving them from a fluid model is
// outside the kernel contract.
struct SpanwiseHydrodynamicRegion {
  double s_min_m = 0.0;
  double s_max_m = 0.0;
  // Global ANCF x/y/z components, in kg/m.
  std::array<double, 3> added_mass_per_length_kg_m{};
  // Global ANCF x/y/z components, in N*s/m^2.
  std::array<double, 3> linear_damping_per_length_Ns_m2{};
};

struct Model {
  double length_m = 10.0;
  double diameter_m = 1.0;
  double inner_diameter_m = 0.9;
  std::size_t elements = 2;
  std::size_t slices = 3;
  std::vector<double> slice_positions_m;
  // Optional versioned distributed-load model metadata.  The legacy model
  // bytes omit this trailer, preserving the historical wire layout.
  SpanwiseLoadReconstruction spanwise_load_reconstruction =
      SpanwiseLoadReconstruction::LegacyPointLumped;
  SpanwiseEndpointPolicy spanwise_endpoint_policy = SpanwiseEndpointPolicy::NearestConstant;
  double spanwise_active_s_min_m = 0.0;
  double spanwise_active_s_max_m = 0.0;
  // Optional SHM1 model extension. Its constant reference-coordinate
  // matrices are resolved once into State during M3 state construction.
  std::vector<SpanwiseHydrodynamicRegion> hydrodynamic_regions;
  double top_tension_N = 1.0e7;
  double youngs_modulus_Pa = 2.07e11;
  double material_density = 7850.0;
  SectionPropertyMode section_property_mode = SectionPropertyMode::LegacyPhysicalSection;
  double explicit_EA_N = 0.0;
  double explicit_EI_Nm2 = 0.0;
  double explicit_mass_per_length_kg_m = 0.0;
  double explicit_displaced_area_m2 = 0.0;
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
  double mass_per_length() const;
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

enum class StaticSolverMode {
  LegacyFixedRelaxation,
  BacktrackingNewton,
  PotentialBacktrackingNewton
};

enum class StaticLoadContract {
  // Caller asserts that Q_ext is fixed for every trial in the current load
  // step and derives from the conservative fixed-load potential contract.
  FixedConservativeGeneralizedLoad
};

struct StaticNewtonTrialDiagnostic {
  double beta = 0.0;
  double residual = 0.0;
  double merit = 0.0;
  double internal_energy = 0.0;
  double delta_potential = 0.0;
  double armijo_rhs = 0.0;
  double r_dot_p = 0.0;
  bool finite = false;
  bool convergence_pass = false;
  bool sufficient_decrease = false;
  std::size_t changed_free_dof_count = 0;
  bool trial_state_unchanged = false;
};

struct StaticNewtonIterationDiagnostic {
  std::size_t load_step = 0;
  std::size_t iteration = 0;
  double residual_before_step = 0.0;
  double residual_normalized_before_step = 0.0;
  double full_newton_direction_norm = 0.0;
  double r_dot_p = 0.0;
  double internal_energy_before = 0.0;
  double beta_accepted = 0.0;
  std::size_t backtrack_count = 0;
  double delta_potential_accepted = 0.0;
  double residual_after_accepted_trial = 0.0;
  double residual_normalized_after_accepted_trial = 0.0;
  bool finite = false;
  bool line_search_failed = false;
  std::vector<StaticNewtonTrialDiagnostic> trials;
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
  std::string failure_reason;
  // Transactionally separate snapshot of the solver's working state. This
  // never commits a failed solve into State::q and is not part of the IPC wire
  // contract.
  bool terminal_state_available = false;
  std::vector<double> terminal_q;
  bool terminal_residual_vector_available = false;
  std::vector<double> terminal_residual;
  std::vector<StaticNewtonIterationDiagnostic> static_newton_trace;
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
  std::vector<std::vector<double>> element_force;
  std::vector<Matrix> element_tangent;
  std::vector<std::vector<double>> global_force_after_element;
  std::vector<Matrix> global_tangent_after_element;
};

// Production assembly may optionally emit this trace.  The callback is
// intentionally data-only: enabling it cannot select a second formula or
// change the arithmetic used by the solver.
struct AssemblyTrace {
  std::vector<ForensicPoint> points;
  std::vector<std::vector<double>> element_force;
  std::vector<Matrix> element_tangent;
  std::vector<std::vector<double>> global_force_after_element;
  std::vector<Matrix> global_tangent_after_element;
};

State make_reference_state(const Model& model);
void validate_model(const Model& model);
// Validate explicit M1 assembler input. Regions must be ordered and
// non-overlapping. Exact touching endpoints are valid; no geometric epsilon
// is applied or introduced by this contract.
void validate_spanwise_hydrodynamic_regions(
    const Model& model, const std::vector<SpanwiseHydrodynamicRegion>& regions);
// Pure regional assemblers. They do not mutate Model or State.
Matrix assemble_spanwise_added_mass(
    const Model& model, const std::vector<SpanwiseHydrodynamicRegion>& regions);
Matrix assemble_spanwise_linear_damping(
    const Model& model, const std::vector<SpanwiseHydrodynamicRegion>& regions);
// Compose the physical dynamic mass from an already-validated base consistent
// mass and the model-defined SHM1 added mass. The external worker mass
// contract supplies this base matrix, never a pre-composed total matrix.
Matrix resolve_total_mass(const Model& model, const Matrix& base_mass);
// Compose the physical damping matrix once for a reconstructed State:
// C = alpha*M_total + beta*K_ref + Ch. resolve_rayleigh_damping remains the
// Rayleigh-only primitive; this helper does not alter its formula.
Matrix resolve_total_damping(const Model& model, const Matrix& total_mass,
                             const std::vector<double>& q_ref,
                             bool require_free_tangent_positive_semidefinite = true);
void symmetrize_mass(State& state);
StepDiagnostics advance(State& state, const Model& model, const std::vector<double>& slice_force,
                        std::vector<NewtonIterationTrace>* trace = nullptr);
StepDiagnostics advance(State& state, const Model& model, const SpanwiseLoadInput& load,
                        std::vector<NewtonIterationTrace>* trace = nullptr);
// Offline-only load-ramped static Newton solve. It shares the production
// internal-force/tangent implementation but intentionally excludes Newmark
// inertia and does not advance state time or step.
StepDiagnostics static_equilibrium(State& state, const Model& model,
                                   const std::vector<double>& base_load,
                                   std::size_t load_steps = 40,
                                   double relaxation = 0.8);
StepDiagnostics static_equilibrium(State& state, const Model& model,
                                   const std::vector<double>& base_load,
                                   std::size_t load_steps,
                                   StaticSolverMode mode);
StepDiagnostics static_equilibrium(State& state, const Model& model,
                                   const std::vector<double>& base_load,
                                   std::size_t load_steps, double relaxation,
                                   StaticSolverMode mode);
StepDiagnostics static_equilibrium(State& state, const Model& model,
                                   const std::vector<double>& base_load,
                                   std::size_t load_steps, StaticSolverMode mode,
                                   StaticLoadContract load_contract);
void internal_force_tangent(const std::vector<double>& q, const Model& model, std::vector<double>& force, Matrix& tangent);
void internal_force_tangent(const std::vector<double>& q, const Model& model, std::vector<double>& force,
                            Matrix& tangent, AssemblyTrace* trace);
// Resolve the constant Rayleigh damping contract from the exact production
// mass matrix and a frozen dynamic-initial reference state.  The optional
// PSD check is applied only to the free-free internal tangent block.
Matrix resolve_rayleigh_damping(const Model& model, const Matrix& mass,
                                const std::vector<double>& q_ref,
                                bool require_free_tangent_positive_semidefinite = true);
ForensicResult internal_force_forensic(const std::vector<double>& q, const Model& model);
std::vector<double> external_force(const Model& model, const std::vector<double>& slice_force);
std::vector<double> external_force(const Model& model, const SpanwiseLoadInput& load);
// Assemble the canonical static gravity/buoyancy/top-tension load used by
// the ANCF initialization contract. This does not alter transient advance.
std::vector<double> static_base_load(const Model& model);
Matrix mapping_H3(const Model& model);
bool finite(const State& state);

}  // namespace cfd_ancf
