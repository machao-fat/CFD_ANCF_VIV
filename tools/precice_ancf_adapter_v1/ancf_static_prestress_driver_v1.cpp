#include "../../src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

namespace {

using cfd_ancf::Matrix;
using cfd_ancf::Model;
using cfd_ancf::State;

constexpr const char* kResultSchema = "ANCF_STATIC_PRESTRESS_RESULT_V1.2";

double norm3(const std::array<double, 3>& value) {
  return std::sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2]);
}

std::string json_escape(const std::string& value) {
  std::string result;
  for (char character : value) {
    switch (character) {
      case '\\': result += "\\\\"; break;
      case '"': result += "\\\""; break;
      case '\n': result += "\\n"; break;
      case '\r': result += "\\r"; break;
      case '\t': result += "\\t"; break;
      default: result.push_back(character); break;
    }
  }
  return result;
}

struct NonfiniteResult : std::runtime_error {
  explicit NonfiniteResult(std::string field)
      : std::runtime_error("nonfinite result field: " + field), fields{std::move(field)} {}
  std::vector<std::string> fields;
};

void require_finite(double value, const std::string& field) {
  if (!std::isfinite(value)) throw NonfiniteResult(field);
}

void require_finite(const std::vector<double>& values, const std::string& field) {
  for (std::size_t index = 0; index < values.size(); ++index)
    require_finite(values[index], field + "[" + std::to_string(index) + "]");
}

void require_finite(const std::array<double, 3>& values, const std::string& field) {
  for (std::size_t index = 0; index < values.size(); ++index)
    require_finite(values[index], field + "[" + std::to_string(index) + "]");
}

bool safe_evaluation_id(const std::string& value) {
  if (value.empty()) return false;
  for (unsigned char character : value) {
    if (!(std::isalnum(character) || character == '_' || character == '-')) return false;
  }
  return true;
}

struct Options {
  std::string result_path;
  std::string evaluation_id;
  bool transport_self_test = false;
  std::string transport_case;
  bool diagnostic_semantics_self_test = false;
};

Options parse_options(int argc, char** argv) {
  Options options;
  for (int index = 1; index < argc; ++index) {
    const std::string argument = argv[index];
    auto next_value = [&](const char* option) {
      if (index + 1 >= argc) throw std::invalid_argument(std::string("missing value for ") + option);
      return std::string(argv[++index]);
    };
    if (argument == "--result-json") {
      options.result_path = next_value("--result-json");
    } else if (argument == "--evaluation-id") {
      options.evaluation_id = next_value("--evaluation-id");
    } else if (argument == "--transport-self-test") {
      options.transport_self_test = true;
      options.transport_case = next_value("--transport-self-test");
    } else if (argument == "--diagnostic-semantics-self-test") {
      options.diagnostic_semantics_self_test = true;
    } else {
      throw std::invalid_argument("unknown option: " + argument);
    }
  }
  if (options.diagnostic_semantics_self_test) return options;
  if (options.result_path.empty()) throw std::invalid_argument("missing --result-json");
  if (!safe_evaluation_id(options.evaluation_id))
    throw std::invalid_argument("evaluation id is empty or unsafe");
  return options;
}

void remove_stale_result(const std::string& result_path) {
  std::error_code error;
  std::filesystem::remove(std::filesystem::path(result_path), error);
  if (error) throw std::runtime_error("cannot remove stale result: " + error.message());
}

void atomic_write_result(const std::string& result_path, const std::string& evaluation_id,
                         const std::string& content) {
  const std::filesystem::path final_path(result_path);
  const std::filesystem::path temporary_path =
      std::filesystem::path(result_path + ".tmp." + evaluation_id);
  std::error_code error;
  std::filesystem::remove(temporary_path, error);
  if (error) throw std::runtime_error("cannot remove temporary result: " + error.message());
  {
    std::ofstream output(temporary_path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("cannot open temporary result");
    output.write(content.data(), static_cast<std::streamsize>(content.size()));
    output.flush();
    if (!output) throw std::runtime_error("cannot flush temporary result");
  }
  error.clear();
  std::filesystem::remove(final_path, error);
  if (error) {
    std::filesystem::remove(temporary_path);
    throw std::runtime_error("cannot replace stale result: " + error.message());
  }
  error.clear();
  std::filesystem::rename(temporary_path, final_path, error);
  if (error) {
    std::filesystem::remove(temporary_path);
    throw std::runtime_error("cannot atomically install result: " + error.message());
  }
}

std::string failure_json(const std::string& evaluation_id, const std::string& classification,
                         const std::string& reason,
                         const std::vector<std::string>& nonfinite_fields = {}) {
  std::ostringstream output;
  output << "{\"schema_version\":\"" << kResultSchema
         << "\",\"evaluation_id\":\"" << json_escape(evaluation_id)
         << "\",\"status\":\"FAIL\",\"static_status\":\"FAIL\""
         << ",\"failure_classification\":\"" << json_escape(classification)
         << "\",\"failure_reason\":\"" << json_escape(reason) << "\"";
  if (!nonfinite_fields.empty()) {
    output << ",\"nonfinite_fields\":[";
    for (std::size_t index = 0; index < nonfinite_fields.size(); ++index) {
      if (index != 0) output << ',';
      output << '"' << json_escape(nonfinite_fields[index]) << '"';
    }
    output << ']';
  }
  output << "}\n";
  return output.str();
}

int emit_failure(const Options& options, const std::string& classification,
                 const std::string& reason,
                 const std::vector<std::string>& nonfinite_fields = {}) {
  try {
    atomic_write_result(options.result_path, options.evaluation_id,
                        failure_json(options.evaluation_id, classification, reason,
                                     nonfinite_fields));
    std::cerr << classification << ": " << reason << '\n';
    return 3;
  } catch (const std::exception& error) {
    std::cerr << "RESULT_WRITE_FAIL: " << error.what() << '\n';
    return 4;
  }
}

std::string transport_pass_json(const std::string& evaluation_id) {
  return std::string("{\"schema_version\":\"") + kResultSchema +
         "\",\"evaluation_id\":\"" + json_escape(evaluation_id) +
         "\",\"status\":\"PASS\",\"static_status\":\"TRANSPORT_TEST\""
         ",\"DeltaL_m\":0,\"H_m\":1,\"top_tension_N\":1"
         ",\"top_reaction_vector_N\":[0,0,1]"
         ",\"bottom_reaction_vector_N\":[0,0,-1]"
         ",\"global_balance_error\":0,\"q\":[0]"
         ",\"potential_diagnostics\":{\"iterations\":0,\"minimum_accepted_beta\":1}}\n";
}

int run_transport_self_test(const Options& options) {
  if (options.transport_case == "stdout_diagnostic")
    std::cout << "transport diagnostic on stdout before result\n";
  if (options.transport_case == "stderr_diagnostic")
    std::cerr << "transport diagnostic on stderr before result\n";
  if (options.transport_case == "nan" || options.transport_case == "inf" ||
      options.transport_case == "neginf") {
    const std::string field = options.transport_case == "nan" ? "q[0]" :
                              options.transport_case == "inf" ? "top_tension_N" :
                                                                "global_balance_error";
    return emit_failure(options, "NONFINITE_STATIC_RESULT", "nonfinite transport test value",
                        {field});
  }
  if (options.transport_case != "valid" && options.transport_case != "stdout_diagnostic" &&
      options.transport_case != "stderr_diagnostic" && options.transport_case != "replace")
    return emit_failure(options, "INVALID_INPUT", "unknown transport self-test case");
  try {
    atomic_write_result(options.result_path, options.evaluation_id,
                        transport_pass_json(options.evaluation_id));
    if (options.transport_case == "stdout_diagnostic")
      std::cout << "transport diagnostic on stdout after result\n";
    if (options.transport_case == "stderr_diagnostic")
      std::cerr << "transport diagnostic on stderr after result\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "RESULT_WRITE_FAIL: " << error.what() << '\n';
    return 4;
  }
}

std::size_t count_non_descent_failures(const cfd_ancf::StepDiagnostics& diagnostics) {
  return diagnostics.failure_reason == "STATIC_POTENTIAL_NON_DESCENT_DIRECTION" ? 1u : 0u;
}

bool run_diagnostic_semantics_self_test() {
  cfd_ancf::StepDiagnostics terminal;
  terminal.converged = true;
  terminal.static_newton_trace.emplace_back();
  if (count_non_descent_failures(terminal) != 0u) return false;

  cfd_ancf::StepDiagnostics beta_one;
  cfd_ancf::StaticNewtonIterationDiagnostic beta_one_record;
  beta_one_record.residual_before_step = 1.0;
  beta_one_record.r_dot_p = -1.0;
  beta_one_record.beta_accepted = 1.0;
  beta_one.static_newton_trace.push_back(beta_one_record);
  if (count_non_descent_failures(beta_one) != 0u) return false;

  cfd_ancf::StepDiagnostics reduced_beta;
  cfd_ancf::StaticNewtonIterationDiagnostic reduced_record;
  reduced_record.residual_before_step = 1.0;
  reduced_record.r_dot_p = -1.0;
  reduced_record.beta_accepted = 0.5;
  reduced_beta.static_newton_trace.push_back(reduced_record);
  if (count_non_descent_failures(reduced_beta) != 0u) return false;

  cfd_ancf::StepDiagnostics non_descent;
  non_descent.failure_reason = "STATIC_POTENTIAL_NON_DESCENT_DIRECTION";
  if (count_non_descent_failures(non_descent) != 1u) return false;

  cfd_ancf::StepDiagnostics line_search;
  line_search.failure_reason = "STATIC_POTENTIAL_LINE_SEARCH_FAILED";
  cfd_ancf::StaticNewtonIterationDiagnostic line_search_record;
  line_search_record.residual_before_step = 1.0;
  line_search_record.r_dot_p = 1.0;
  line_search_record.line_search_failed = true;
  line_search.static_newton_trace.push_back(line_search_record);
  if (count_non_descent_failures(line_search) != 0u) return false;

  cfd_ancf::StepDiagnostics inactive;
  cfd_ancf::StaticNewtonIterationDiagnostic inactive_record;
  inactive_record.r_dot_p = 0.0;
  inactive_record.residual_before_step = 2.0;
  inactive.static_newton_trace.push_back(inactive_record);
  return count_non_descent_failures(inactive) == 0u;
}

void write_array(std::ostream& output, const std::vector<double>& values) {
  output << '[' << std::setprecision(17);
  for (std::size_t index = 0; index < values.size(); ++index) {
    if (index != 0) output << ',';
    output << values[index];
  }
  output << ']';
}

void write_array(std::ostream& output, const std::array<double, 3>& values) {
  output << '[' << std::setprecision(17) << values[0] << ',' << values[1] << ',' << values[2] << ']';
}

struct Request {
  int section_mode = 0;
  int base_load_mode = 1;
  std::size_t elements = 0;
  double length_m = 0.0;
  double youngs_modulus_Pa = 0.0;
  double diameter_m = 0.0;
  double inner_diameter_m = 0.0;
  double material_density = 0.0;
  double explicit_EA_N = 0.0;
  double explicit_EI_Nm2 = 0.0;
  double explicit_mass_per_length_kg_m = 0.0;
  double explicit_displaced_area_m2 = 0.0;
  double fluid_density = 0.0;
  double gravity = 0.0;
  double dt_s = 0.0;
  double beta = 0.0;
  double gamma = 0.0;
  double newton_tolerance = 0.0;
  std::size_t max_newton = 0;
  std::size_t gauss_order = 0;
  std::size_t mass_gauss_order = 0;
  std::size_t load_steps = 0;
  double delta_length_m = 0.0;
  std::array<double, 3> bottom{};
  std::array<double, 3> axis{};
  std::vector<double> caller_base_load;
};

Request read_request() {
  Request request;
  if (!(std::cin >> request.section_mode >> request.base_load_mode >> request.elements >>
        request.length_m >> request.youngs_modulus_Pa >> request.diameter_m >>
        request.inner_diameter_m >> request.material_density >> request.explicit_EA_N >>
        request.explicit_EI_Nm2 >> request.explicit_mass_per_length_kg_m >>
        request.explicit_displaced_area_m2 >> request.fluid_density >> request.gravity >>
        request.dt_s >> request.beta >> request.gamma >> request.newton_tolerance >>
        request.max_newton >> request.gauss_order >> request.mass_gauss_order >>
        request.load_steps >> request.delta_length_m >> request.bottom[0] >> request.bottom[1] >>
        request.bottom[2] >> request.axis[0] >> request.axis[1] >> request.axis[2])) {
    throw std::invalid_argument("prestress driver request header is incomplete");
  }
  std::size_t base_count = 0;
  if (!(std::cin >> base_count)) throw std::invalid_argument("prestress driver base-load count is missing");
  if (request.base_load_mode == 0) {
    request.caller_base_load.resize(base_count);
    for (double& value : request.caller_base_load) {
      if (!(std::cin >> value)) throw std::invalid_argument("prestress driver base-load vector is incomplete");
    }
  } else if (base_count != 0) {
    throw std::invalid_argument("model-static request must not carry a caller base-load vector");
  }
  return request;
}

Model make_model(const Request& request) {
  Model model;
  model.length_m = request.length_m;
  model.diameter_m = request.diameter_m;
  model.inner_diameter_m = request.inner_diameter_m;
  model.elements = request.elements;
  model.slices = 1;
  model.slice_positions_m = {0.0};
  model.top_tension_N = 0.0;
  model.youngs_modulus_Pa = request.youngs_modulus_Pa;
  model.material_density = request.material_density;
  model.fluid_density = request.fluid_density;
  model.gravity = request.gravity;
  model.dt_s = request.dt_s;
  model.beta = request.beta;
  model.gamma = request.gamma;
  model.newton_tolerance = request.newton_tolerance;
  model.max_newton = request.max_newton;
  model.gauss_order = request.gauss_order;
  model.mass_gauss_order = request.mass_gauss_order;
  model.boundary_contract_id = "prestress_position_both_ends_v1";
  model.fixed_dof = {0u, 1u, 2u, 6u * request.elements,
                     6u * request.elements + 1u, 6u * request.elements + 2u};
  model.prescribed_values.resize(6);
  model.prescribed_values[0] = request.bottom[0];
  model.prescribed_values[1] = request.bottom[1];
  model.prescribed_values[2] = request.bottom[2];
  const double height = request.length_m + request.delta_length_m;
  for (std::size_t component = 0; component < 3; ++component)
    model.prescribed_values[3 + component] = request.bottom[component] + request.axis[component] * height;
  if (request.section_mode == 1) {
    model.section_property_mode = cfd_ancf::SectionPropertyMode::ExplicitSectionProperties;
    model.explicit_EA_N = request.explicit_EA_N;
    model.explicit_EI_Nm2 = request.explicit_EI_Nm2;
    model.explicit_mass_per_length_kg_m = request.explicit_mass_per_length_kg_m;
    model.explicit_displaced_area_m2 = request.explicit_displaced_area_m2;
  } else if (request.section_mode != 0) {
    throw std::invalid_argument("prestress driver section mode is invalid");
  }
  return model;
}

State make_installed_state(const Model& model, const Request& request) {
  State state = cfd_ancf::make_reference_state(model);
  const double stretch = (request.length_m + request.delta_length_m) / request.length_m;
  for (std::size_t node = 0; node <= request.elements; ++node) {
    const std::size_t offset = 6u * node;
    const double material_s = request.length_m * static_cast<double>(node) /
                              static_cast<double>(request.elements);
    for (std::size_t component = 0; component < 3; ++component) {
      state.q[offset + component] = request.bottom[component] + request.axis[component] * stretch * material_s;
      state.q[offset + 3u + component] = request.axis[component] * stretch;
    }
  }
  return state;
}

}  // namespace

int main(int argc, char** argv) {
  Options options;
  try {
    options = parse_options(argc, argv);
    if (options.diagnostic_semantics_self_test)
      return run_diagnostic_semantics_self_test() ? 0 : 5;
    remove_stale_result(options.result_path);
    if (options.transport_self_test) return run_transport_self_test(options);
    const Request request = read_request();
    const Model model = make_model(request);
    cfd_ancf::validate_model(model);
    const std::size_t n = model.ndof();
    if (request.base_load_mode != 0 && request.base_load_mode != 1)
      throw std::invalid_argument("prestress driver base-load mode is invalid");
    if (request.base_load_mode == 0 && request.caller_base_load.size() != n)
      throw std::invalid_argument("caller base-load vector dimension mismatch");
    State state = make_installed_state(model, request);
    std::vector<double> base_load = request.base_load_mode == 1
        ? cfd_ancf::static_base_load(model) : request.caller_base_load;
    const auto diagnostics = cfd_ancf::static_equilibrium(
        state, model, base_load, request.load_steps,
        cfd_ancf::StaticSolverMode::PotentialBacktrackingNewton,
        cfd_ancf::StaticLoadContract::FixedConservativeGeneralizedLoad);
    if (!diagnostics.converged) {
      return emit_failure(options, diagnostics.failure_reason.empty()
                                      ? "STATIC_SOLVER_NONCONVERGENCE"
                                      : diagnostics.failure_reason,
                          diagnostics.failure_reason.empty()
                              ? "static Newton solve did not converge"
                              : diagnostics.failure_reason);
    }
    std::vector<double> internal;
    Matrix tangent;
    cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
    const std::size_t top = 6u * request.elements;
    std::array<double, 3> bottom_reaction{};
    std::array<double, 3> top_reaction{};
    std::array<double, 3> external_total{};
    for (std::size_t component = 0; component < 3; ++component) {
      bottom_reaction[component] = internal[component] - base_load[component];
      top_reaction[component] = internal[top + component] - base_load[top + component];
    }
    for (std::size_t node = 0; node <= request.elements; ++node) {
      for (std::size_t component = 0; component < 3; ++component)
        external_total[component] += base_load[6u * node + component];
    }
    std::array<double, 3> balance{};
    for (std::size_t component = 0; component < 3; ++component)
      balance[component] = top_reaction[component] + bottom_reaction[component] + external_total[component];
    const double balance_numerator = norm3(balance);
    const double balance_denominator = (std::max)(1.0, norm3(top_reaction) +
                                                   norm3(bottom_reaction) + norm3(external_total));
    const double global_balance_error = balance_numerator / balance_denominator;
    double max_abs_lambda_minus_1 = 0.0;
    for (std::size_t node = 0; node <= request.elements; ++node) {
      const std::size_t offset = 6u * node + 3u;
      const double lambda = std::sqrt(state.q[offset] * state.q[offset] +
                                      state.q[offset + 1] * state.q[offset + 1] +
                                      state.q[offset + 2] * state.q[offset + 2]);
      max_abs_lambda_minus_1 = (std::max)(max_abs_lambda_minus_1, std::abs(lambda - 1.0));
    }
    double minimum_beta = (std::numeric_limits<double>::infinity)();
    std::size_t maximum_backtracks = 0;
    const std::size_t non_descent_failures = count_non_descent_failures(diagnostics);
    std::size_t line_search_failures = 0;
    std::size_t unchanged_seen = 0;
    std::size_t unchanged_accepted = 0;
    for (const auto& iteration : diagnostics.static_newton_trace) {
      if (iteration.line_search_failed) ++line_search_failures;
      if (iteration.beta_accepted > 0.0) {
        minimum_beta = (std::min)(minimum_beta, iteration.beta_accepted);
        maximum_backtracks = (std::max)(maximum_backtracks, iteration.backtrack_count);
      }
      for (const auto& trial : iteration.trials) {
        if (trial.trial_state_unchanged) ++unchanged_seen;
        if (trial.trial_state_unchanged && trial.beta == iteration.beta_accepted) ++unchanged_accepted;
      }
    }
    if (!std::isfinite(minimum_beta)) minimum_beta = 0.0;
    const double height = request.length_m + request.delta_length_m;
    const double top_tension = norm3(top_reaction);
    const double normalized_residual = diagnostics.residual / diagnostics.residual_scale;
    require_finite(model.length_m, "length_m");
    require_finite(request.delta_length_m, "DeltaL_m");
    require_finite(height, "H_m");
    require_finite(model.EA(), "EA_N");
    require_finite(model.EI(), "EI_Nm2");
    require_finite(model.mass_per_length(), "mass_per_length_kg_m");
    require_finite(model.displaced_area(), "displaced_area_m2");
    require_finite(diagnostics.residual, "residual");
    require_finite(diagnostics.residual_scale, "residual_scale");
    require_finite(normalized_residual, "normalized_residual");
    require_finite(top_tension, "top_tension_N");
    require_finite(top_reaction, "top_reaction_vector_N");
    require_finite(bottom_reaction, "bottom_reaction_vector_N");
    require_finite(external_total, "external_total_N");
    require_finite(global_balance_error, "global_balance_error");
    require_finite(max_abs_lambda_minus_1, "max_abs_lambda_minus_1");
    require_finite(minimum_beta, "minimum_accepted_beta");
    require_finite(base_load, "base_load");
    require_finite(state.q, "q");
    require_finite(state.qdot, "qdot");
    require_finite(state.qddot, "qddot");
    std::ostringstream output;
    output << std::setprecision(17)
           << "{\"schema_version\":\"" << kResultSchema
           << "\",\"evaluation_id\":\"" << json_escape(options.evaluation_id)
           << "\",\"status\":\"PASS\",\"static_status\":\"CONVERGED\""
           << ",\"failure_reason\":\"\",\"finite\":true"
           << ",\"elements\":" << model.elements
           << ",\"length_m\":" << model.length_m
           << ",\"DeltaL_m\":" << request.delta_length_m
           << ",\"H_m\":" << height
           << ",\"delta_length_m\":" << request.delta_length_m
           << ",\"height_m\":" << height
           << ",\"EA_N\":" << model.EA()
           << ",\"EI_Nm2\":" << model.EI()
           << ",\"mass_per_length_kg_m\":" << model.mass_per_length()
           << ",\"displaced_area_m2\":" << model.displaced_area()
           << ",\"iterations\":" << diagnostics.iterations
           << ",\"residual\":" << diagnostics.residual
           << ",\"residual_scale\":" << diagnostics.residual_scale
           << ",\"normalized_residual\":" << normalized_residual
           << ",\"top_tension_N\":" << top_tension
           << ",\"top_reaction_vector_N\":";
    write_array(output, top_reaction);
    output << ",\"bottom_reaction_vector_N\":";
    write_array(output, bottom_reaction);
    output << ",\"top_reaction\":";
    write_array(output, top_reaction);
    output << ",\"bottom_reaction\":";
    write_array(output, bottom_reaction);
    output << ",\"external_total\":";
    write_array(output, external_total);
    output << ",\"global_balance_error\":" << global_balance_error
           << ",\"max_abs_lambda_minus_1\":" << max_abs_lambda_minus_1
           << ",\"minimum_accepted_beta\":" << minimum_beta
           << ",\"maximum_backtrack_depth\":" << maximum_backtracks
           << ",\"non_descent_failures\":" << non_descent_failures
           << ",\"line_search_failures\":" << line_search_failures
           << ",\"unchanged_trials_seen\":" << unchanged_seen
           << ",\"unchanged_trials_accepted\":" << unchanged_accepted
           << ",\"base_load\":";
    write_array(output, base_load);
    output << ",\"q\":";
    write_array(output, state.q);
    output << ",\"qdot\":";
    write_array(output, state.qdot);
    output << ",\"qddot\":";
    write_array(output, state.qddot);
    output << ",\"potential_diagnostics\":{\"iterations\":" << diagnostics.iterations
           << ",\"residual\":" << diagnostics.residual
           << ",\"residual_scale\":" << diagnostics.residual_scale
           << ",\"normalized_residual\":" << normalized_residual
           << ",\"minimum_accepted_beta\":" << minimum_beta
           << ",\"maximum_backtrack_depth\":" << maximum_backtracks
           << ",\"non_descent_failures\":" << non_descent_failures
           << ",\"line_search_failures\":" << line_search_failures
           << ",\"unchanged_trials_seen\":" << unchanged_seen
           << ",\"unchanged_trials_accepted\":" << unchanged_accepted << "}}\n";
    atomic_write_result(options.result_path, options.evaluation_id, output.str());
    return 0;
  } catch (const NonfiniteResult& error) {
    return emit_failure(options, "NONFINITE_STATIC_RESULT", error.what(), error.fields);
  } catch (const std::exception& error) {
    if (!options.result_path.empty() && safe_evaluation_id(options.evaluation_id))
      return emit_failure(options, "INVALID_INPUT", error.what());
    std::cerr << "INVALID_INPUT: " << error.what() << '\n';
    return 2;
  }
}
