#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace cfd_ancf;

namespace {

bool close(double left, double right, double tolerance = 1.0e-10) {
  return std::abs(left - right) <= tolerance * std::max({1.0, std::abs(left), std::abs(right)});
}

Model synthetic_model() {
  Model model;
  model.length_m = 1.0;
  model.diameter_m = 0.05;
  model.inner_diameter_m = 0.04;
  model.elements = 2;
  model.slices = 1;
  model.top_tension_N = 0.0;
  model.youngs_modulus_Pa = 2.0e9;
  model.material_density = 4000.0;
  model.fluid_density = 1000.0;
  model.gravity = 9.81;
  model.dt_s = 0.00125;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  model.fixed_dof = {0u, 1u, 2u, 6u * model.elements, 6u * model.elements + 1u};
  model.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0};
  return model;
}

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

double measured_decay(double alpha, double beta, double target_zeta) {
  Model model = synthetic_model();
  model.dt_s = 5.0e-4;
  model.boundary_contract_id = "structural_damping_scalar_test_v1";
  const State reference = make_reference_state(model);
  const std::size_t free_dof = 7u;
  model.fixed_dof.clear();
  model.prescribed_values.clear();
  for (std::size_t index = 0; index < model.ndof(); ++index) {
    if (index != free_dof) {
      model.fixed_dof.push_back(index);
      model.prescribed_values.push_back(reference.q[index]);
    }
  }
  std::vector<double> internal;
  Matrix tangent;
  internal_force_tangent(reference.q, model, internal, tangent);
  const double omega = std::sqrt(tangent(free_dof, free_dof) / reference.mass(free_dof, free_dof));
  require(std::isfinite(omega) && omega > 0.0, "scalar validation mode is not stable");
  model.damping_alpha = alpha;
  model.damping_beta = beta;
  State state = make_reference_state(model);
  state.damping = resolve_rayleigh_damping(model, state.mass, reference.q);
  state.q[free_dof] += 1.0e-4;
  std::vector<double> peaks;
  std::vector<double> samples;
  const std::size_t steps = 4000;
  for (std::size_t step = 0; step < steps; ++step) {
    const StepDiagnostics diagnostics = advance(state, model, {0.0, 0.0, 0.0});
    require(diagnostics.converged, "scalar free-decay step did not converge");
    samples.push_back(state.q[free_dof] - reference.q[free_dof]);
  }
  for (std::size_t index = 1; index + 1 < samples.size(); ++index) {
    if (samples[index] > samples[index - 1] && samples[index] >= samples[index + 1] && samples[index] > 0.0)
      peaks.push_back(samples[index]);
  }
  require(peaks.size() >= 3u, "scalar free-decay did not produce enough peaks");
  const double log_decrement = std::log(peaks.front() / peaks.back()) /
                               static_cast<double>(peaks.size() - 1u);
  const double pi = std::acos(-1.0);
  const double measured = log_decrement / std::sqrt(4.0 * pi * pi + log_decrement * log_decrement);
  require(std::abs(measured - target_zeta) <= 0.003, "free-decay damping ratio mismatch");
  return measured;
}

}  // namespace

int main() {
  try {
    const Model base = synthetic_model();
    const State reference = make_reference_state(base);
    const std::size_t n = base.ndof();

    Model none_model = base;
    const Matrix none = resolve_rayleigh_damping(none_model, reference.mass, reference.q);
    require(std::all_of(none.data.begin(), none.data.end(), [](double value) { return value == 0.0; }),
            "none damping is not exactly zero");

    Model mass_model = base;
    mass_model.damping_alpha = 0.25;
    const Matrix mass_damping = resolve_rayleigh_damping(mass_model, reference.mass, reference.q);
    for (std::size_t row = 0; row < n; ++row)
      for (std::size_t col = 0; col < n; ++col)
        require(close(mass_damping(row, col), 0.25 * reference.mass(row, col)), "mass damping mismatch");

    Model stiffness_model = base;
    stiffness_model.damping_beta = 1.0e-7;
    const Matrix stiffness_damping = resolve_rayleigh_damping(stiffness_model, reference.mass, reference.q);
    Model mixed_model = base;
    mixed_model.damping_alpha = 0.25;
    mixed_model.damping_beta = 1.0e-7;
    const Matrix mixed_damping = resolve_rayleigh_damping(mixed_model, reference.mass, reference.q);
    for (std::size_t row = 0; row < n; ++row) {
      for (std::size_t col = 0; col < n; ++col) {
        require(close(mixed_damping(row, col), mass_damping(row, col) + stiffness_damping(row, col)),
                "mixed damping mismatch");
        require(close(stiffness_damping(row, col), stiffness_damping(col, row)), "damping is not symmetric");
      }
    }

    const Matrix frozen_again = resolve_rayleigh_damping(stiffness_model, reference.mass, reference.q);
    for (std::size_t index = 0; index < n * n; ++index)
      require(close(frozen_again.data[index], stiffness_damping.data[index]), "reference tangent was not frozen");

    Model prestressed_model = base;
    prestressed_model.damping_alpha = 0.25;
    prestressed_model.damping_beta = 1.0e-7;
    std::vector<double> q_static = reference.q;
    for (std::size_t node = 0; node <= prestressed_model.elements; ++node) {
      q_static[6 * node + 2] *= 1.01;
      q_static[6 * node + 5] = 1.01;
    }
    const Matrix prestressed_damping = resolve_rayleigh_damping(
        prestressed_model, reference.mass, q_static);
    require(std::all_of(prestressed_damping.data.begin(), prestressed_damping.data.end(),
                        [](double value) { return std::isfinite(value); }),
            "prestressed reference damping is non-finite");

    State dynamic = reference;
    dynamic.qdot[7] = 0.01;
    dynamic.damping = mass_damping;
    const StepDiagnostics dynamic_diagnostics = advance(dynamic, mass_model, {0.0, 0.0, 0.0});
    require(dynamic_diagnostics.converged, "damped structural step did not converge");
    require(std::isfinite(dynamic.residual) && std::isfinite(dynamic.time_s), "damped state is non-finite");

    Model compressed = base;
    std::vector<double> q_compressed = reference.q;
    for (std::size_t node = 0; node <= compressed.elements; ++node)
      q_compressed[6 * node + 5] *= 0.5;
    compressed.damping_beta = 1.0e-7;
    bool rejected_indefinite = false;
    try {
      (void)resolve_rayleigh_damping(compressed, reference.mass, q_compressed);
    } catch (const std::exception& error) {
      rejected_indefinite = std::string(error.what()).find("DAMPING_REFERENCE_TANGENT_NOT_PSD") != std::string::npos;
    }
    require(rejected_indefinite, "indefinite reference tangent was not rejected");

    Model scalar = synthetic_model();
    scalar.boundary_contract_id = "structural_damping_scalar_test_v1";
    const State scalar_reference = make_reference_state(scalar);
    std::vector<double> scalar_internal;
    Matrix scalar_tangent;
    scalar.fixed_dof.clear();
    scalar.prescribed_values.clear();
    for (std::size_t index = 0; index < scalar.ndof(); ++index) {
      if (index != 7u) {
        scalar.fixed_dof.push_back(index);
        scalar.prescribed_values.push_back(scalar_reference.q[index]);
      }
    }
    internal_force_tangent(scalar_reference.q, scalar, scalar_internal, scalar_tangent);
    const double omega = std::sqrt(scalar_tangent(7, 7) / scalar_reference.mass(7, 7));
    const double target_zeta = 0.01;
    const double mass_decay = measured_decay(2.0 * target_zeta * omega, 0.0, target_zeta);
    const double stiffness_decay = measured_decay(0.0, 2.0 * target_zeta / omega, target_zeta);
    const double mixed_decay = measured_decay(target_zeta * omega, target_zeta / omega, target_zeta);

    Model static_none_model = synthetic_model();
    Model static_damped_model = static_none_model;
    static_damped_model.damping_alpha = 0.25;
    State static_none = make_reference_state(static_none_model);
    State static_damped = make_reference_state(static_damped_model);
    const std::vector<double> static_load(static_none_model.ndof(), 0.0);
    const StepDiagnostics static_none_diagnostics = static_equilibrium(
        static_none, static_none_model, static_load, 1, StaticSolverMode::PotentialBacktrackingNewton,
        StaticLoadContract::FixedConservativeGeneralizedLoad);
    const StepDiagnostics static_damped_diagnostics = static_equilibrium(
        static_damped, static_damped_model, static_load, 1, StaticSolverMode::PotentialBacktrackingNewton,
        StaticLoadContract::FixedConservativeGeneralizedLoad);
    require(static_none_diagnostics.converged && static_damped_diagnostics.converged,
            "static zero-load comparison did not converge");
    require(static_none.q == static_damped.q, "damping metadata changed static q");

    Model explicit_model = base;
    explicit_model.section_property_mode = SectionPropertyMode::ExplicitSectionProperties;
    explicit_model.explicit_EA_N = base.EA();
    explicit_model.explicit_EI_Nm2 = base.EI();
    explicit_model.explicit_mass_per_length_kg_m = base.mass_per_length();
    explicit_model.explicit_displaced_area_m2 = base.displaced_area();
    explicit_model.damping_alpha = 0.25;
    explicit_model.damping_beta = 1.0e-7;
    const State explicit_reference = make_reference_state(explicit_model);
    const Matrix explicit_damping = resolve_rayleigh_damping(
        explicit_model, explicit_reference.mass, explicit_reference.q);
    const Matrix legacy_damping = mixed_damping;
    require(explicit_reference.mass.data.size() == reference.mass.data.size(), "section mass size mismatch");
    for (std::size_t index = 0; index < legacy_damping.data.size(); ++index)
      require(close(explicit_damping.data[index], legacy_damping.data[index]), "legacy/explicit damping mismatch");
    double dissipation = 0.0;
    const auto test_vector = [](std::size_t index) {
      if (index == 0u || index == 1u || index == 2u || index == 12u || index == 13u) return 0.0;
      return (index % 5u == 0u) ? 1.0 : -0.25;
    };
    for (std::size_t row = 0; row < mixed_damping.rows; ++row) {
      for (std::size_t col = 0; col < mixed_damping.cols; ++col) {
        dissipation += test_vector(row) * mixed_damping(row, col) * test_vector(col);
      }
    }
    require(std::isfinite(dissipation) && dissipation >= -1.0e-10,
            "dissipation test is negative");

    std::cout << "C_MATRIX_TEST=PASS\n"
              << "REFERENCE_FREEZE_TEST=PASS\n"
              << "PRESTRESSED_REFERENCE_TEST=PASS\n"
              << "DAMPED_STEP_TEST=PASS\n"
              << "PSD_REJECTION_TEST=PASS\n"
              << "MASS_DECAY_TEST=PASS measured_zeta=" << mass_decay << "\n"
              << "STIFFNESS_DECAY_TEST=PASS measured_zeta=" << stiffness_decay << "\n"
              << "MIXED_DECAY_TEST=PASS measured_zeta=" << mixed_decay << "\n"
              << "STATIC_INVARIANCE_TEST=PASS\n"
              << "LEGACY_EXPLICIT_TEST=PASS\n"
              << "DISSIPATION_FINITE_TEST=PASS value=" << dissipation << "\n"
              << "dynamic_iterations=" << dynamic_diagnostics.iterations << "\n"
              << "dynamic_residual=" << dynamic_diagnostics.residual << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "STRUCTURAL_DAMPING_KERNEL_TEST_FAIL: " << error.what() << '\n';
    return 1;
  }
}
