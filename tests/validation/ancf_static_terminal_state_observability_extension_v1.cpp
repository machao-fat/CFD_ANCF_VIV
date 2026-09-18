#include "ancf_kernel.hpp"
#include "sha256.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using cfd_ancf::Matrix;
using cfd_ancf::Model;
using cfd_ancf::State;
using cfd_ancf::StaticLoadContract;
using cfd_ancf::StaticSolverMode;
using cfd_ancf::StepDiagnostics;

constexpr double kConsistencyTolerance = 1.0e-12;

Model make_model() {
  Model model;
  model.length_m = 1.0;
  model.diameter_m = 0.05;
  model.inner_diameter_m = 0.04;
  model.elements = 2;
  model.slices = 3;
  model.top_tension_N = 0.0;
  model.youngs_modulus_Pa = 2.0e9;
  model.material_density = 4000.0;
  model.fluid_density = 1000.0;
  model.gravity = 0.0;
  model.include_gravity = true;
  model.include_buoyancy = true;
  model.max_newton = 1;
  model.newton_tolerance = 1.0e-14;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  model.fixed_dof = {0, 1, 2, 3, 4, 5};
  model.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0, 1.0};
  model.boundary_contract_id = "static_terminal_observability_test_root_clamp_v1";
  cfd_ancf::validate_model(model);
  return model;
}

std::vector<double> make_tip_load(const Model& model) {
  std::vector<double> load(model.ndof(), 0.0);
  load[6 * model.elements] = 1.0e-3;
  return load;
}

std::vector<double> masked_residual(const std::vector<double>& q, const Model& model,
                                    const std::vector<double>& load) {
  std::vector<double> internal;
  Matrix tangent;
  cfd_ancf::internal_force_tangent(q, model, internal, tangent);
  std::vector<char> fixed(model.ndof(), 0);
  for (std::size_t i = 0; i < model.fixed_dof.size(); ++i) fixed[model.fixed_dof[i]] = 1;
  std::vector<double> residual(model.ndof(), 0.0);
  for (std::size_t i = 0; i < model.ndof(); ++i)
    residual[i] = fixed[i] ? 0.0 : internal[i] - load[i];
  return residual;
}

double inf_norm(const std::vector<double>& values) {
  double result = 0.0;
  for (double value : values) result = (std::max)(result, std::abs(value));
  return result;
}

double max_abs_difference(const std::vector<double>& lhs,
                         const std::vector<double>& rhs) {
  if (lhs.size() != rhs.size()) return std::numeric_limits<double>::infinity();
  double result = 0.0;
  for (std::size_t i = 0; i < lhs.size(); ++i)
    result = (std::max)(result, std::abs(lhs[i] - rhs[i]));
  return result;
}

std::string sha256_vector(const std::vector<double>& values) {
  std::vector<unsigned char> bytes(values.size() * sizeof(double));
  if (!bytes.empty()) std::memcpy(bytes.data(), values.data(), bytes.size());
  std::array<unsigned char, 32> digest{};
  if (!cfd_ancf::wire::sha256_bytes(bytes, digest))
    throw std::runtime_error("SHA-256 calculation failed");
  std::ostringstream out;
  out << std::uppercase << std::hex << std::setfill('0');
  for (unsigned char value : digest) out << std::setw(2) << static_cast<unsigned>(value);
  return out.str();
}

void write_json(const std::filesystem::path& path, const std::string& body) {
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  if (!output) throw std::runtime_error("cannot write observability test output");
  output << body << "\n";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: observability_selftest <output-directory>\n";
    return 2;
  }
  try {
    const std::filesystem::path output_dir(argv[1]);
    const Model model = make_model();
    const std::vector<double> load = make_tip_load(model);

    State failed_state = cfd_ancf::make_reference_state(model);
    const State failed_state_before = failed_state;
    const StepDiagnostics failed = cfd_ancf::static_equilibrium(
        failed_state, model, load, 1, StaticSolverMode::PotentialBacktrackingNewton,
        StaticLoadContract::FixedConservativeGeneralizedLoad);
    const std::vector<double> recomputed_failed_residual =
        masked_residual(failed.terminal_q, model, load);
    const double failed_residual_error =
        max_abs_difference(failed.terminal_residual, recomputed_failed_residual);
    const double failed_norm_error =
        std::abs(inf_norm(recomputed_failed_residual) - failed.residual);
    const double failed_normalized = failed.residual / failed.residual_scale;
    const bool failed_state_unchanged = failed_state.q == failed_state_before.q;
    const bool failed_progress = failed.terminal_q != failed_state_before.q;
    const bool failed_consistent =
        failed.terminal_state_available && failed.terminal_residual_vector_available &&
        failed.terminal_q.size() == model.ndof() &&
        failed.terminal_residual.size() == model.ndof() &&
        failed_state_unchanged && failed_progress &&
        std::isfinite(failed.residual) && std::isfinite(failed.residual_scale) &&
        std::isfinite(failed_normalized) && failed_residual_error <= kConsistencyTolerance &&
        failed_norm_error <= kConsistencyTolerance;
    if (failed.converged || failed.failure_reason.empty() || !failed_consistent)
      throw std::runtime_error("failed-path transactional observability contract failed");

    Model success_model = model;
    success_model.max_newton = 1;
    success_model.newton_tolerance = 1.0e-8;
    State success_state = cfd_ancf::make_reference_state(success_model);
    const std::vector<double> zero_load(success_model.ndof(), 0.0);
    const StepDiagnostics success = cfd_ancf::static_equilibrium(
        success_state, success_model, zero_load, 1,
        StaticSolverMode::PotentialBacktrackingNewton,
        StaticLoadContract::FixedConservativeGeneralizedLoad);
    const std::vector<double> recomputed_success_residual =
        masked_residual(success_state.q, success_model, zero_load);
    const double success_residual_error =
        max_abs_difference(success.terminal_residual, recomputed_success_residual);
    const bool success_identity =
        success.converged && success.terminal_state_available &&
        success.terminal_residual_vector_available &&
        success.terminal_q == success_state.q &&
        success.terminal_residual.size() == success_model.ndof() &&
        success_residual_error <= kConsistencyTolerance;
    if (!success_identity) throw std::runtime_error("success-path snapshot contract failed");

    write_json(output_dir / "ANCF_STATIC_TERMINAL_STATE_OBSERVABILITY_EXTENSION_V1_FAILURE_PATH_TEST.json",
               "{\n"
               "  \"status\": \"PASS\",\n"
               "  \"failure_reason\": \"" + failed.failure_reason + "\",\n"
               "  \"caller_state_unchanged\": " + (failed_state_unchanged ? "true" : "false") + ",\n"
               "  \"terminal_state_available\": " + (failed.terminal_state_available ? "true" : "false") + ",\n"
               "  \"terminal_q_differs_from_caller_state\": " + (failed_progress ? "true" : "false") + ",\n"
               "  \"terminal_q_sha256\": \"" + sha256_vector(failed.terminal_q) + "\",\n"
               "  \"terminal_q_size\": " + std::to_string(failed.terminal_q.size()) + ",\n"
               "  \"terminal_residual_vector_available\": " +
                   (failed.terminal_residual_vector_available ? "true" : "false") + ",\n"
               "  \"residual\": " + std::to_string(failed.residual) + ",\n"
               "  \"residual_scale\": " + std::to_string(failed.residual_scale) + ",\n"
               "  \"normalized_residual\": " + std::to_string(failed_normalized) + ",\n"
               "  \"recomputed_residual_inf\": " + std::to_string(inf_norm(recomputed_failed_residual)) + ",\n"
               "  \"residual_vector_max_abs_error\": " + std::to_string(failed_residual_error) + ",\n"
               "  \"residual_norm_abs_error\": " + std::to_string(failed_norm_error) + ",\n"
               "  \"consistency_tolerance\": " + std::to_string(kConsistencyTolerance) + "\n"
               "}");
    write_json(output_dir / "ANCF_STATIC_TERMINAL_STATE_OBSERVABILITY_EXTENSION_V1_SUCCESS_PATH_TEST.json",
               "{\n"
               "  \"status\": \"PASS\",\n"
               "  \"converged\": true,\n"
               "  \"terminal_state_available\": true,\n"
               "  \"terminal_q_equals_committed_state_q\": true,\n"
               "  \"terminal_q_sha256\": \"" + sha256_vector(success.terminal_q) + "\",\n"
               "  \"terminal_residual_vector_available\": true,\n"
               "  \"residual_vector_max_abs_error\": " + std::to_string(success_residual_error) + ",\n"
               "  \"consistency_tolerance\": " + std::to_string(kConsistencyTolerance) + "\n"
               "}");

    std::cout << "static_terminal_state_observability_selftest=pass\n"
              << "failure_reason=" << failed.failure_reason << "\n"
              << "failure_terminal_q_sha256=" << sha256_vector(failed.terminal_q) << "\n"
              << "success_terminal_q_sha256=" << sha256_vector(success.terminal_q) << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "static_terminal_state_observability_selftest=fail: " << error.what() << "\n";
    return 1;
  }
}
