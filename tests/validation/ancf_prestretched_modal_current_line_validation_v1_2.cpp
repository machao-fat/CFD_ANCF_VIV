#define main ancf_prestretched_modal_current_line_validation_v1_original_main
#include "ancf_prestretched_modal_current_line_validation_v1.cpp"
#undef main

#include <filesystem>
#include <sstream>

namespace {

std::string json_number(double value) {
  if (!std::isfinite(value)) return "null";
  std::ostringstream out;
  out << std::setprecision(17) << value;
  return out.str();
}

void atomic_write_v12(const std::string& path, const std::string& text) {
  const std::string temporary = path + ".tmp";
  std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("D_EVIDENCE_SERIALIZATION_FAIL");
  out.write(text.data(), static_cast<std::streamsize>(text.size()));
  out.flush();
  if (!out) throw std::runtime_error("D_EVIDENCE_SERIALIZATION_FAIL");
  out.close();
  std::error_code error;
  std::filesystem::rename(temporary, path, error);
  if (error) throw std::runtime_error("D_EVIDENCE_SERIALIZATION_FAIL");
}

std::string static_json_v12(const cfd_ancf::StepDiagnostics& diag,
                            double normalized, double fixed_error,
                            double root_x, double root_y, double root_z,
                            double top_x, double top_y,
                            double balance_x, double balance_y, double balance_z,
                            double balance_norm, double top_z, double delta) {
  std::ostringstream out;
  out << std::setprecision(17)
      << "{\n"
      << "  \"converged\": " << (diag.converged ? "true" : "false") << ",\n"
      << "  \"iterations\": " << diag.iterations << ",\n"
      << "  \"initial_residual\": " << json_number(diag.initial_residual) << ",\n"
      << "  \"residual\": " << json_number(diag.residual) << ",\n"
      << "  \"residual_scale\": " << json_number(diag.residual_scale) << ",\n"
      << "  \"normalized_residual\": " << json_number(normalized) << ",\n"
      << "  \"failure_reason\": \"" << (diag.failure_reason.empty() ? "none" : diag.failure_reason) << "\",\n"
      << "  \"max_fixed_error\": " << json_number(fixed_error) << ",\n"
      << "  \"root_reaction_xyz\": [" << json_number(root_x) << ", " << json_number(root_y) << ", " << json_number(root_z) << "],\n"
      << "  \"top_reaction_xy\": [" << json_number(top_x) << ", " << json_number(top_y) << "],\n"
      << "  \"global_balance_xyz\": [" << json_number(balance_x) << ", " << json_number(balance_y) << ", " << json_number(balance_z) << "],\n"
      << "  \"global_balance_norm\": " << json_number(balance_norm) << ",\n"
      << "  \"prestretch_top_z_m\": " << json_number(top_z) << ",\n"
      << "  \"prestretch_delta_m\": " << json_number(delta) << ",\n"
      << "  \"zero_damping\": {\"mode\": \"none\", \"alpha\": 0.0, \"beta\": 0.0}\n"
      << "}\n";
  return out.str();
}

std::string identity_header_v12(const cfd_ancf::State& state,
                                const cfd_ancf::Matrix& mass_ff,
                                const cfd_ancf::Matrix& tangent,
                                const cfd_ancf::Matrix& tangent_ff,
                                const std::vector<std::size_t>& free) {
  std::ostringstream out;
  out << "{\n"
      << "  \"q_count\": " << state.q.size() << ",\n"
      << "  \"M_full\": {\"rows\": " << state.mass.rows << ", \"cols\": " << state.mass.cols << "},\n"
      << "  \"M_ff\": {\"rows\": " << mass_ff.rows << ", \"cols\": " << mass_ff.cols << "},\n"
      << "  \"K_full\": {\"rows\": " << tangent.rows << ", \"cols\": " << tangent.cols << "},\n"
      << "  \"K_ff\": {\"rows\": " << tangent_ff.rows << ", \"cols\": " << tangent_ff.cols << "},\n"
      << "  \"free_dof_count\": " << free.size() << ",\n"
      << "  \"production_generated\": true,\n"
      << "  \"zero_damping\": true\n"
      << "}\n";
  return out.str();
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 9) {
    std::cerr << "usage: modal_v1_2 <static.json> <matrix_identity.json> <q> <Mfull> <Mff> <Kfull> <Kff> <free>\n";
    return 2;
  }
  try {
    const cfd_ancf::Model model = make_model();
    cfd_ancf::State state = cfd_ancf::make_reference_state(model);
    const std::vector<double> base_load = cfd_ancf::static_base_load(model);
    const cfd_ancf::StepDiagnostics static_diag =
        cfd_ancf::static_equilibrium(state, model, base_load, LoadSteps, StaticRelaxation);

    const std::vector<std::size_t> fixed = {0u, 1u, 2u, 6u * Elements, 6u * Elements + 1u};
    double max_fixed_error = 0.0;
    const double prescribed[] = {0.0, 0.0, 0.0, 0.0, 0.0};
    for (std::size_t i = 0; i < fixed.size(); ++i)
      max_fixed_error = (std::max)(max_fixed_error, std::abs(state.q[fixed[i]] - prescribed[i]));
    const double normalized = static_diag.residual / static_diag.residual_scale;

    std::vector<double> internal;
    cfd_ancf::Matrix tangent;
    if (static_diag.converged && cfd_ancf::finite(state))
      cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
    else {
      atomic_write_v12(argv[1], static_json_v12(static_diag, normalized, max_fixed_error,
          0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0));
      throw std::runtime_error("D_PRESTRESS_EQUILIBRIUM_FAIL");
    }

    std::vector<double> reaction(internal.size(), 0.0);
    for (std::size_t i = 0; i < reaction.size(); ++i) reaction[i] = internal[i] - base_load[i];
    const std::size_t top = 6u * Elements;
    const double root_x = reaction[0], root_y = reaction[1], root_z = reaction[2];
    const double top_x = reaction[top], top_y = reaction[top + 1u];
    double external_x = 0.0, external_y = 0.0, external_z = 0.0;
    for (std::size_t node = 0; node <= Elements; ++node) {
      const std::size_t dof = 6u * node;
      external_x += base_load[dof];
      external_y += base_load[dof + 1u];
      external_z += base_load[dof + 2u];
    }
    const double balance_x = external_x + root_x + top_x;
    const double balance_y = external_y + root_y + top_y;
    const double balance_z = external_z + root_z;
    const double balance_norm = std::sqrt(balance_x * balance_x + balance_y * balance_y + balance_z * balance_z);
    const double top_z = state.q[top + 2u];
    const double delta = top_z - model.length_m;
    const auto free = free_y_dof(model);
    const cfd_ancf::Matrix mass_ff = select(state.mass, free);
    const cfd_ancf::Matrix tangent_ff = select(tangent, free);

    write_vector(argv[3], state.q);
    write_matrix(argv[4], state.mass);
    write_matrix(argv[5], mass_ff);
    write_matrix(argv[6], tangent);
    write_matrix(argv[7], tangent_ff);
    write_indices(argv[8], free);
    atomic_write_v12(argv[1], static_json_v12(static_diag, normalized, max_fixed_error,
        root_x, root_y, root_z, top_x, top_y, balance_x, balance_y, balance_z,
        balance_norm, top_z, delta));
    atomic_write_v12(argv[2], identity_header_v12(state, mass_ff, tangent, tangent_ff, free));

    std::cout << std::setprecision(17)
              << "status PRODUCTION_STATE_MATRICES_WRITTEN\n"
              << "static_converged " << (static_diag.converged ? 1 : 0)
              << " static_iterations " << static_diag.iterations
              << " static_residual " << static_diag.residual
              << " residual_scale " << static_diag.residual_scale
              << " normalized_residual " << normalized
              << " max_fixed_error " << max_fixed_error
              << " global_balance_norm " << balance_norm
              << " prestretch_top_z_m " << top_z
              << " prestretch_delta_m " << delta << '\n'
              << "q_count " << state.q.size()
              << " M_full " << state.mass.rows << 'x' << state.mass.cols
              << " M_ff " << mass_ff.rows << 'x' << mass_ff.cols
              << " K_full " << tangent.rows << 'x' << tangent.cols
              << " K_ff " << tangent_ff.rows << 'x' << tangent_ff.cols
              << " free_count " << free.size() << '\n'
              << "zero_damping alpha 0 beta 0\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
