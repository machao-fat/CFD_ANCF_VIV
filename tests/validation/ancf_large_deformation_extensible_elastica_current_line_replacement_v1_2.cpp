#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr double Length = 1.0;
constexpr double EAValue = 100.0;
constexpr double EIValue = 1.0;
constexpr double MassPerLength = 1.0;
constexpr double DisplacedArea = 1.0e-3;
constexpr double TipLoad = 2.0;
constexpr std::size_t LoadSteps = 80u;
constexpr std::size_t MaxNewton = 50u;
constexpr double NewtonTolerance = 1.0e-8;

cfd_ancf::Model make_model(std::size_t elements) {
  cfd_ancf::Model model;
  model.length_m = Length;
  model.diameter_m = 0.05;
  model.inner_diameter_m = 0.04;
  model.elements = elements;
  model.slices = 3;
  model.top_tension_N = 0.0;
  model.youngs_modulus_Pa = 1.0;
  model.material_density = 1.0;
  model.section_property_mode = cfd_ancf::SectionPropertyMode::ExplicitSectionProperties;
  model.explicit_EA_N = EAValue;
  model.explicit_EI_Nm2 = EIValue;
  model.explicit_mass_per_length_kg_m = MassPerLength;
  model.explicit_displaced_area_m2 = DisplacedArea;
  model.fluid_density = 1000.0;
  model.gravity = 0.0;
  model.include_gravity = true;
  model.include_buoyancy = true;
  model.dt_s = 0.00125;
  model.beta = 0.25;
  model.gamma = 0.5;
  model.max_newton = MaxNewton;
  model.newton_tolerance = NewtonTolerance;
  model.damping_alpha = 0.0;
  model.damping_beta = 0.0;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  // Per-node ordering is [r_x,r_y,r_z,r_Sx,r_Sy,r_Sz]. The continuum
  // reference leaves the root axial stretch free, so only five root
  // components are prescribed. All tip components remain free.
  model.fixed_dof = {0u, 1u, 2u, 3u, 4u};
  model.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0};
  model.boundary_contract_id = "ancf_f_v1_2_root_position_and_tangent_direction";
  cfd_ancf::validate_model(model);
  return model;
}

std::vector<double> make_dead_tip_load(const cfd_ancf::Model& model) {
  std::vector<double> load(model.ndof(), 0.0);
  load[6u * model.elements] = TipLoad;
  return load;
}

double max_fixed_error(const cfd_ancf::State& state, const cfd_ancf::Model& model) {
  double result = 0.0;
  const double prescribed[] = {0.0, 0.0, 0.0, 0.0, 0.0};
  for (std::size_t i = 0; i < model.fixed_dof.size(); ++i)
    result = (std::max)(result, std::abs(state.q[model.fixed_dof[i]] - prescribed[i]));
  return result;
}

double max_position_displacement(const cfd_ancf::State& state,
                                 const cfd_ancf::Model& model) {
  double result = 0.0;
  const double Le = model.length_m / static_cast<double>(model.elements);
  for (std::size_t node = 0; node <= model.elements; ++node) {
    const std::size_t base = 6u * node;
    const double dz = state.q[base + 2u] - static_cast<double>(node) * Le;
    const double dx = state.q[base];
    const double dy = state.q[base + 1u];
    result = (std::max)(result, std::sqrt(dx * dx + dy * dy + dz * dz));
  }
  return result;
}

void write_nodes(const std::string& path, const cfd_ancf::State& state,
                 const cfd_ancf::Model& model) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("F_EVIDENCE_SERIALIZATION_FAIL");
  out << std::setprecision(17) << "node,S,x,y,z,rs_x,rs_y,rs_z\n";
  const double Le = model.length_m / static_cast<double>(model.elements);
  for (std::size_t node = 0; node <= model.elements; ++node) {
    const std::size_t base = 6u * node;
    out << node << ',' << static_cast<double>(node) * Le << ','
        << state.q[base] << ',' << state.q[base + 1u] << ',' << state.q[base + 2u]
        << ',' << state.q[base + 3u] << ',' << state.q[base + 4u] << ','
        << state.q[base + 5u] << '\n';
  }
}

void write_diagnostics(const std::string& path, const cfd_ancf::StepDiagnostics& d,
                       const cfd_ancf::State& state, const cfd_ancf::Model& model,
                       const std::vector<double>& load) {
  std::vector<double> internal;
  cfd_ancf::Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  std::vector<double> reaction(internal.size(), 0.0);
  for (std::size_t i = 0; i < reaction.size(); ++i) reaction[i] = internal[i] - load[i];
  const std::size_t root = 0u;
  const std::size_t tip = 6u * model.elements;
  const double balance_x = reaction[root] + TipLoad;
  const double balance_y = reaction[root + 1u];
  const double balance_z = reaction[root + 2u];
  const double balance_norm = std::sqrt(balance_x * balance_x + balance_y * balance_y +
                                        balance_z * balance_z);
  std::size_t non_descent = 0u, line_search_failures = 0u, max_backtracks = 0u;
  double min_beta = std::numeric_limits<double>::infinity();
  for (const auto& iteration : d.static_newton_trace) {
    if (!std::isfinite(iteration.r_dot_p) || iteration.r_dot_p >= 0.0) ++non_descent;
    if (iteration.line_search_failed) ++line_search_failures;
    max_backtracks = (std::max)(max_backtracks, iteration.backtrack_count);
    if (iteration.beta_accepted > 0.0)
      min_beta = (std::min)(min_beta, iteration.beta_accepted);
  }
  if (!std::isfinite(min_beta)) min_beta = 0.0;
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("F_EVIDENCE_SERIALIZATION_FAIL");
  out << std::setprecision(17)
      << "{\"elements\":" << model.elements
      << ",\"ndof\":" << model.ndof()
      << ",\"boundary_contract_id\":\"" << model.boundary_contract_id << "\""
      << ",\"constrained_dofs\":[0,1,2,3,4]"
      << ",\"tip_x_dof\":" << tip
      << ",\"converged\":" << (d.converged ? "true" : "false")
      << ",\"iterations\":" << d.iterations
      << ",\"load_steps\":" << LoadSteps
      << ",\"residual\":" << d.residual
      << ",\"residual_scale\":" << d.residual_scale
      << ",\"normalized_residual\":" << d.residual / d.residual_scale
      << ",\"failure_reason\":\"" << d.failure_reason << "\""
      << ",\"non_descent_failures\":" << non_descent
      << ",\"line_search_failures\":" << line_search_failures
      << ",\"minimum_accepted_beta\":" << min_beta
      << ",\"maximum_backtrack_depth\":" << max_backtracks
      << ",\"maximum_displacement\":" << max_position_displacement(state, model)
      << ",\"fixed_error\":" << max_fixed_error(state, model)
      << ",\"root_reaction_xyz\":[" << reaction[root] << ',' << reaction[root + 1u]
      << ',' << reaction[root + 2u] << ']'
      << ",\"root_gradient_reaction\":[" << reaction[3u] << ',' << reaction[4u]
      << ',' << reaction[5u] << ']'
      << ",\"tip_y_reaction\":" << reaction[tip + 1u]
      << ",\"balance_xyz\":[" << balance_x << ',' << balance_y << ',' << balance_z << ']'
      << ",\"balance_norm\":" << balance_norm
      << ",\"free_load_projection_norm\":" << TipLoad
      << ",\"constrained_load_projection_norm\":0"
      << ",\"zero_damping\":true}\n";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 5 || std::string(argv[1]) != "mesh") {
    std::cerr << "usage: elastica mesh <elements> <nodes.csv> <diagnostics.json>\n";
    return 2;
  }
  try {
    const std::size_t elements = static_cast<std::size_t>(std::stoull(argv[2]));
    const auto model = make_model(elements);
    auto state = cfd_ancf::make_reference_state(model);
    const auto load = make_dead_tip_load(model);
    const auto diagnostic = cfd_ancf::static_equilibrium(
        state, model, load, LoadSteps,
        cfd_ancf::StaticSolverMode::PotentialBacktrackingNewton,
        cfd_ancf::StaticLoadContract::FixedConservativeGeneralizedLoad);
    write_diagnostics(argv[4], diagnostic, state, model, load);
    if (!diagnostic.converged || !cfd_ancf::finite(state))
      throw std::runtime_error("F_STATIC_SOLVE_FAIL");
    write_nodes(argv[3], state, model);
    std::cout << std::setprecision(17)
              << "status PASS elements " << elements
              << " iterations " << diagnostic.iterations
              << " residual " << diagnostic.residual
              << " residual_scale " << diagnostic.residual_scale
              << " normalized_residual " << diagnostic.residual / diagnostic.residual_scale
              << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
