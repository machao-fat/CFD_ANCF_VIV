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

using cfd_ancf::Matrix;
using cfd_ancf::Model;
using cfd_ancf::SectionPropertyMode;
using cfd_ancf::State;
using cfd_ancf::StaticLoadContract;
using cfd_ancf::StaticNewtonIterationDiagnostic;
using cfd_ancf::StaticSolverMode;
using cfd_ancf::StepDiagnostics;

namespace {

constexpr double L = 1.0;
constexpr double D = 0.05;
constexpr double Di = 0.04;
constexpr double E = 2.0e9;
constexpr double RhoMaterial = 4000.0;
constexpr double RhoFluid = 1000.0;
constexpr double Gravity = 0.0;
constexpr double Eta = 1.0e-3;
constexpr std::size_t LoadSteps = 40;
constexpr double TipTol = 1.0e-4;
constexpr double SlopeTol = 2.0e-4;
constexpr double ShapeTol = 2.0e-4;
constexpr double BalanceTol = 1.0e-9;
constexpr double TipStabilityTol = 1.0e-4;
constexpr double SlopeStabilityTol = 2.0e-4;

const double Iref = 3.141592653589793238462643383279502884 *
                    (D * D * D * D - Di * Di * Di * Di) / 64.0;
const double EIref = E * Iref;
const double P = 3.0 * EIref * Eta / (L * L);
const double DeltaRef = P * L * L * L / (3.0 * EIref);
const double ThetaRef = P * L * L / (2.0 * EIref);

struct ShapeRow {
  std::size_t elements = 0;
  std::size_t node = 0;
  double z = 0.0;
  double x_num = 0.0;
  double x_ref = 0.0;
  double error = 0.0;
};

struct MeshResult {
  std::size_t elements = 0;
  bool converged = false;
  std::size_t iterations = 0;
  double residual = 0.0;
  double residual_scale = 0.0;
  double normalized_residual = 0.0;
  std::string failure_reason;
  std::size_t non_descent_failures = 0;
  std::size_t line_search_failures = 0;
  double minimum_accepted_beta = 0.0;
  std::size_t maximum_backtrack_depth = 0;
  double tip_delta = 0.0;
  double tip_theta = 0.0;
  double tip_error = 0.0;
  double theta_error = 0.0;
  double shape_error = 0.0;
  double root_reaction_x = 0.0;
  double root_reaction_y = 0.0;
  double root_reaction_z = 0.0;
  double balance_error = 0.0;
  double max_abs_transverse_displacement = 0.0;
  std::vector<ShapeRow> shape;
};

bool finite(double value) { return std::isfinite(value); }

double x_eb(double z) {
  return P * z * z * (3.0 * L - z) / (6.0 * EIref);
}

double theta_eb(double z) {
  return P * z * (2.0 * L - z) / (2.0 * EIref);
}

Model make_model(std::size_t elements) {
  Model model;
  model.length_m = L;
  model.diameter_m = D;
  model.inner_diameter_m = Di;
  model.elements = elements;
  model.section_property_mode = SectionPropertyMode::LegacyPhysicalSection;
  model.youngs_modulus_Pa = E;
  model.material_density = RhoMaterial;
  model.fluid_density = RhoFluid;
  model.gravity = Gravity;
  model.include_gravity = true;
  model.include_buoyancy = true;
  model.top_tension_N = 0.0;
  model.dt_s = 0.00125;
  model.beta = 0.25;
  model.gamma = 0.5;
  model.max_newton = 40;
  model.newton_tolerance = 1.0e-8;
  model.damping_alpha = 0.0;
  model.damping_beta = 0.0;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  model.boundary_contract_id = "ancf_current_line_c_cantilever_clamp_v1";
  model.fixed_dof = {0, 1, 2, 3, 4, 5};
  model.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0, 1.0};
  cfd_ancf::validate_model(model);
  return model;
}

std::vector<double> make_load(const Model& model) {
  std::vector<double> load(model.ndof(), 0.0);
  load[6 * model.elements] = P;
  return load;
}

MeshResult run_mesh(std::size_t elements) {
  const Model model = make_model(elements);
  State state = cfd_ancf::make_reference_state(model);
  const std::vector<double> load = make_load(model);
  const StepDiagnostics diagnostics = cfd_ancf::static_equilibrium(
      state, model, load, LoadSteps, StaticSolverMode::PotentialBacktrackingNewton,
      StaticLoadContract::FixedConservativeGeneralizedLoad);

  MeshResult result;
  result.elements = elements;
  result.converged = diagnostics.converged;
  result.iterations = diagnostics.iterations;
  result.residual = diagnostics.residual;
  result.residual_scale = diagnostics.residual_scale;
  result.normalized_residual = diagnostics.residual_scale > 0.0
                                   ? diagnostics.residual / diagnostics.residual_scale
                                   : std::numeric_limits<double>::quiet_NaN();
  result.failure_reason = diagnostics.failure_reason;
  if (diagnostics.failure_reason == "STATIC_POTENTIAL_NON_DESCENT_DIRECTION")
    result.non_descent_failures = 1;
  double minimum_beta = std::numeric_limits<double>::infinity();
  for (const StaticNewtonIterationDiagnostic& iteration : diagnostics.static_newton_trace) {
    if (iteration.line_search_failed) ++result.line_search_failures;
    result.maximum_backtrack_depth =
        (std::max)(result.maximum_backtrack_depth, iteration.backtrack_count);
    if (iteration.beta_accepted > 0.0)
      minimum_beta = (std::min)(minimum_beta, iteration.beta_accepted);
  }
  result.minimum_accepted_beta = std::isfinite(minimum_beta) ? minimum_beta : 0.0;

  if (!result.converged) return result;
  if (!cfd_ancf::finite(state))
    throw std::runtime_error("C_NONFINITE_RESULT: static state is not finite");

  std::vector<double> internal;
  Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  const std::size_t tip = 6 * model.elements;
  result.tip_delta = state.q[tip];
  result.tip_theta = std::atan2(state.q[tip + 3], state.q[tip + 5]);
  result.tip_error = std::abs(result.tip_delta - DeltaRef) / std::abs(DeltaRef);
  result.theta_error = std::abs(result.tip_theta - ThetaRef) / std::abs(ThetaRef);

  double shape_numerator = 0.0;
  double shape_denominator = 0.0;
  for (std::size_t node = 1; node <= model.elements; ++node) {
    const double z = L * static_cast<double>(node) / static_cast<double>(model.elements);
    const double x_num = state.q[6 * node];
    const double x_ref = x_eb(z);
    const double difference = x_num - x_ref;
    shape_numerator += difference * difference;
    shape_denominator += x_ref * x_ref;
    result.max_abs_transverse_displacement =
        (std::max)(result.max_abs_transverse_displacement, std::abs(x_num));
    result.shape.push_back({elements, node, z, x_num, x_ref, difference});
  }
  result.shape_error = std::sqrt(shape_numerator / shape_denominator);

  const std::vector<double> reaction = [&]() {
    std::vector<double> value(model.ndof(), 0.0);
    for (std::size_t i = 0; i < model.ndof(); ++i) value[i] = internal[i] - load[i];
    return value;
  }();
  result.root_reaction_x = reaction[0];
  result.root_reaction_y = reaction[1];
  result.root_reaction_z = reaction[2];
  result.balance_error = std::abs(result.root_reaction_x + P) / (std::max)(std::abs(P), 1.0e-30);
  return result;
}

void json_number(std::ostream& out, double value) {
  if (finite(value)) out << std::setprecision(17) << value;
  else out << "null";
}

void write_result(const std::string& path, const std::vector<MeshResult>& results,
                 const std::string& status, const std::string& classification) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write result JSON");
  out << "{\n";
  out << "  \"schema_version\": \"ANCF_C_CURRENT_LINE_REPLACEMENT_V1\",\n";
  out << "  \"status\": \"" << status << "\",\n";
  out << "  \"classification\": \"" << classification << "\",\n";
  out << "  \"elements_sequence\": [2,4,8,16],\n";
  out << "  \"I_ref_m4\": "; json_number(out, Iref); out << ",\n";
  out << "  \"EI_ref_Nm2\": "; json_number(out, EIref); out << ",\n";
  out << "  \"eta\": "; json_number(out, Eta); out << ",\n";
  out << "  \"P_N\": "; json_number(out, P); out << ",\n";
  out << "  \"delta_tip_ref_m\": "; json_number(out, DeltaRef); out << ",\n";
  out << "  \"theta_tip_ref_rad\": "; json_number(out, ThetaRef); out << ",\n";
  out << "  \"meshes\": [\n";
  for (std::size_t index = 0; index < results.size(); ++index) {
    const MeshResult& result = results[index];
    out << "    {\"elements\": " << result.elements
        << ", \"converged\": " << (result.converged ? "true" : "false")
        << ", \"iterations\": " << result.iterations
        << ", \"residual\": "; json_number(out, result.residual);
    out << ", \"residual_scale\": "; json_number(out, result.residual_scale);
    out << ", \"normalized_residual\": "; json_number(out, result.normalized_residual);
    out << ", \"failure_reason\": \"" << result.failure_reason << "\""
        << ", \"non_descent_failures\": " << result.non_descent_failures
        << ", \"line_search_failures\": " << result.line_search_failures
        << ", \"minimum_accepted_beta\": "; json_number(out, result.minimum_accepted_beta);
    out << ", \"maximum_backtrack_depth\": " << result.maximum_backtrack_depth
        << ", \"tip_delta_m\": "; json_number(out, result.tip_delta);
    out << ", \"tip_theta_rad\": "; json_number(out, result.tip_theta);
    out << ", \"tip_error\": "; json_number(out, result.tip_error);
    out << ", \"theta_error\": "; json_number(out, result.theta_error);
    out << ", \"shape_error\": "; json_number(out, result.shape_error);
    out << ", \"root_reaction_x_N\": "; json_number(out, result.root_reaction_x);
    out << ", \"root_reaction_y_N\": "; json_number(out, result.root_reaction_y);
    out << ", \"root_reaction_z_N\": "; json_number(out, result.root_reaction_z);
    out << ", \"balance_error\": "; json_number(out, result.balance_error);
    out << ", \"max_abs_transverse_displacement_m\": ";
    json_number(out, result.max_abs_transverse_displacement);
    out << "}" << (index + 1 == results.size() ? "\n" : ",\n");
  }
  out << "  ],\n";
  bool all_converged = results.size() == 4;
  for (const MeshResult& result : results) all_converged = all_converged && result.converged;
  const MeshResult* finest = nullptr;
  const MeshResult* coarse_finest = nullptr;
  for (const MeshResult& result : results) {
    if (result.elements == 16) finest = &result;
    if (result.elements == 8) coarse_finest = &result;
  }
  const bool gates = all_converged && finest != nullptr && coarse_finest != nullptr &&
                     finest->tip_error <= TipTol && finest->theta_error <= SlopeTol &&
                     finest->shape_error <= ShapeTol && finest->balance_error <= BalanceTol &&
                     std::abs(coarse_finest->tip_delta - finest->tip_delta) /
                             std::abs(finest->tip_delta) <= TipStabilityTol &&
                     std::abs(coarse_finest->tip_theta - finest->tip_theta) /
                             std::abs(finest->tip_theta) <= SlopeStabilityTol;
  out << "  \"gates\": {\n"
      << "    \"all_meshes_converged\": " << (all_converged ? "true" : "false") << ",\n"
      << "    \"tip_16\": " << (finest != nullptr && finest->tip_error <= TipTol ? "true" : "false") << ",\n"
      << "    \"slope_16\": " << (finest != nullptr && finest->theta_error <= SlopeTol ? "true" : "false") << ",\n"
      << "    \"shape_16\": " << (finest != nullptr && finest->shape_error <= ShapeTol ? "true" : "false") << ",\n"
      << "    \"balance\": " << (finest != nullptr && finest->balance_error <= BalanceTol ? "true" : "false") << ",\n"
      << "    \"stabilization_8_to_16\": " << (gates ? "true" : "false") << "\n"
      << "  },\n"
      << "  \"root_moment_gate\": \"NOT_USED_CONTRACT_NOT_PROVEN\",\n"
      << "  \"final_status\": \"" << (gates ? "PASS" : "FAIL") << "\"\n"
      << "}\n";
}

void write_mesh_csv(const std::string& path, const std::vector<MeshResult>& results) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write mesh CSV");
  out << "elements,converged,iterations,residual,residual_scale,normalized_residual,"
         "failure_reason,non_descent_failures,line_search_failures,minimum_accepted_beta,"
         "maximum_backtrack_depth,tip_delta_m,tip_theta_rad,tip_error,theta_error,shape_error,"
         "root_reaction_x_N,root_reaction_y_N,root_reaction_z_N,balance_error,max_abs_transverse_displacement_m\n";
  for (const MeshResult& result : results) {
    out << result.elements << ',' << (result.converged ? 1 : 0) << ',' << result.iterations << ',';
    out << std::setprecision(17);
    out << result.residual << ',' << result.residual_scale << ',' << result.normalized_residual << ','
        << result.failure_reason << ',' << result.non_descent_failures << ','
        << result.line_search_failures << ',' << result.minimum_accepted_beta << ','
        << result.maximum_backtrack_depth << ',' << result.tip_delta << ',' << result.tip_theta << ','
        << result.tip_error << ',' << result.theta_error << ',' << result.shape_error << ','
        << result.root_reaction_x << ',' << result.root_reaction_y << ',' << result.root_reaction_z << ','
        << result.balance_error << ',' << result.max_abs_transverse_displacement << '\n';
  }
}

void write_shape_csv(const std::string& path, const std::vector<MeshResult>& results) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write shape CSV");
  out << "elements,node,z_m,x_num_m,x_ref_m,error_m\n";
  out << std::setprecision(17);
  for (const MeshResult& result : results)
    for (const ShapeRow& row : result.shape)
      out << row.elements << ',' << row.node << ',' << row.z << ',' << row.x_num << ','
          << row.x_ref << ',' << row.error << '\n';
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: cantilever <result.json> <mesh.csv> <shape.csv>\n";
    return 2;
  }
  std::vector<MeshResult> results;
  std::string status = "PASS";
  std::string classification = "";
  try {
    for (const std::size_t elements : {std::size_t(2), std::size_t(4), std::size_t(8), std::size_t(16)}) {
      MeshResult result = run_mesh(elements);
      results.push_back(result);
      std::cout << "mesh=" << elements << " converged=" << (result.converged ? "true" : "false")
                << " iterations=" << result.iterations << " residual=" << std::setprecision(17)
                << result.residual << " tip_delta=" << result.tip_delta
                << " tip_theta=" << result.tip_theta << " tip_error=" << result.tip_error
                << " theta_error=" << result.theta_error << " shape_error=" << result.shape_error
                << " balance_error=" << result.balance_error << '\n';
      if (!result.converged) {
        status = "FAIL";
        classification = "C_STATIC_SOLVE_FAIL";
        break;
      }
    }
    write_mesh_csv(argv[2], results);
    write_shape_csv(argv[3], results);
    write_result(argv[1], results, status, classification);
    bool final_pass = false;
    if (results.size() == 4) {
      const MeshResult& r8 = results[2];
      const MeshResult& r16 = results[3];
      final_pass = r16.tip_error <= TipTol && r16.theta_error <= SlopeTol &&
                   r16.shape_error <= ShapeTol && r16.balance_error <= BalanceTol &&
                   std::abs(r8.tip_delta - r16.tip_delta) / std::abs(r16.tip_delta) <= TipStabilityTol &&
                   std::abs(r8.tip_theta - r16.tip_theta) / std::abs(r16.tip_theta) <= SlopeStabilityTol;
    }
    if (!final_pass && status == "PASS") {
      std::cout << "final_gate=FAIL\n";
      return 1;
    }
    std::cout << "final_gate=" << (final_pass ? "PASS" : "FAIL") << "\n";
    return status == "PASS" && final_pass ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    try {
      write_mesh_csv(argv[2], results);
      write_shape_csv(argv[3], results);
      write_result(argv[1], results, "FAIL", "C_NONFINITE_RESULT");
    } catch (...) {
    }
    return 1;
  }
}
