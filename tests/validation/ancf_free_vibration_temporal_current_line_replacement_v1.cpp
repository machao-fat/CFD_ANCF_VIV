#include <filesystem>
#include <sstream>

#define main ancf_prestretched_modal_current_line_validation_v1_original_main
#include "ancf_prestretched_modal_current_line_validation_v1.cpp"
#undef main

namespace {

using cfd_ancf::Matrix;
namespace fs = std::filesystem;

constexpr std::size_t ElementsForCase = 16u;
constexpr double PerturbationAmplitude = 1.0e-4;

std::vector<double> read_vector(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("cannot read vector evidence");
  std::vector<double> values;
  double value = 0.0;
  while (in >> value) values.push_back(value);
  if (!in.eof()) throw std::runtime_error("invalid vector evidence");
  return values;
}

Matrix read_matrix(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("cannot read matrix evidence");
  std::vector<std::vector<double>> rows;
  std::string line;
  std::size_t columns = 0;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    std::istringstream row_stream(line);
    std::vector<double> row;
    double value = 0.0;
    while (row_stream >> value) row.push_back(value);
    if (row.empty()) throw std::runtime_error("invalid matrix evidence row");
    if (columns == 0) columns = row.size();
    if (row.size() != columns) throw std::runtime_error("ragged matrix evidence");
    rows.push_back(row);
  }
  Matrix result(rows.size(), columns);
  for (std::size_t r = 0; r < rows.size(); ++r)
    for (std::size_t c = 0; c < columns; ++c) result(r, c) = rows[r][c];
  return result;
}

std::vector<std::size_t> read_indices(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("cannot read index evidence");
  std::vector<std::size_t> values;
  std::size_t value = 0;
  while (in >> value) values.push_back(value);
  if (!in.eof()) throw std::runtime_error("invalid index evidence");
  return values;
}

std::vector<double> solve_dense(Matrix matrix, std::vector<double> rhs) {
  if (matrix.rows != matrix.cols || matrix.rows != rhs.size())
    throw std::invalid_argument("linear solve dimensions");
  const std::size_t n = matrix.rows;
  for (std::size_t col = 0; col < n; ++col) {
    std::size_t pivot = col;
    for (std::size_t row = col + 1; row < n; ++row)
      if (std::abs(matrix(row, col)) > std::abs(matrix(pivot, col))) pivot = row;
    if (!std::isfinite(matrix(pivot, col)) || std::abs(matrix(pivot, col)) <= 1.0e-300)
      throw std::runtime_error("initial acceleration mass solve is singular");
    if (pivot != col) {
      for (std::size_t j = col; j < n; ++j) std::swap(matrix(col, j), matrix(pivot, j));
      std::swap(rhs[col], rhs[pivot]);
    }
    for (std::size_t row = col + 1; row < n; ++row) {
      const double factor = matrix(row, col) / matrix(col, col);
      matrix(row, col) = 0.0;
      for (std::size_t j = col + 1; j < n; ++j) matrix(row, j) -= factor * matrix(col, j);
      rhs[row] -= factor * rhs[col];
    }
  }
  std::vector<double> result(n, 0.0);
  for (std::size_t row = n; row-- > 0;) {
    double value = rhs[row];
    for (std::size_t col = row + 1; col < n; ++col) value -= matrix(row, col) * result[col];
    result[row] = value / matrix(row, row);
  }
  return result;
}

Matrix select_rows_cols(const Matrix& source, const std::vector<std::size_t>& indices) {
  return select(source, indices);
}

std::vector<double> select_vector(const std::vector<double>& source,
                                  const std::vector<std::size_t>& indices) {
  std::vector<double> result(indices.size());
  for (std::size_t i = 0; i < indices.size(); ++i) result[i] = source[indices[i]];
  return result;
}

std::vector<std::size_t> dynamic_free_dof(const std::size_t ndof) {
  const std::vector<std::size_t> fixed = {0u, 1u, 2u, 6u * ElementsForCase,
                                          6u * ElementsForCase + 1u};
  std::vector<char> is_fixed(ndof, 0);
  for (const std::size_t index : fixed) is_fixed[index] = 1;
  std::vector<std::size_t> result;
  for (std::size_t i = 0; i < ndof; ++i) if (!is_fixed[i]) result.push_back(i);
  return result;
}

double max_constraint_error(const cfd_ancf::State& state) {
  const std::vector<std::size_t> fixed = {0u, 1u, 2u, 6u * ElementsForCase,
                                          6u * ElementsForCase + 1u};
  double value = 0.0;
  for (const std::size_t index : fixed) {
    value = (std::max)(value, std::abs(state.q[index]));
    value = (std::max)(value, std::abs(state.qdot[index]));
    value = (std::max)(value, std::abs(state.qddot[index]));
  }
  return value;
}

void write_static_json(const std::string& path, const cfd_ancf::StepDiagnostics& d,
                       const cfd_ancf::State& state, const cfd_ancf::Model& model,
                       double fixed_error, double balance_norm, double prestretch) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write static diagnostics");
  out << std::setprecision(17)
      << "{\"converged\":" << (d.converged ? "true" : "false")
      << ",\"iterations\":" << d.iterations
      << ",\"residual\":" << d.residual
      << ",\"residual_scale\":" << d.residual_scale
      << ",\"normalized_residual\":" << d.residual / d.residual_scale
      << ",\"failure_reason\":\"" << d.failure_reason << "\""
      << ",\"max_fixed_error\":" << fixed_error
      << ",\"global_balance_norm\":" << balance_norm
      << ",\"prestretch_delta_m\":" << prestretch
      << ",\"ndof\":" << model.ndof()
      << ",\"zero_damping\":true}\n";
}

void run_setup(const std::string& output_dir) {
  fs::create_directories(output_dir);
  const cfd_ancf::Model model = make_model();
  cfd_ancf::State state = cfd_ancf::make_reference_state(model);
  const std::vector<double> base_load = cfd_ancf::static_base_load(model);
  const cfd_ancf::StepDiagnostics diagnostic =
      cfd_ancf::static_equilibrium(state, model, base_load, LoadSteps, StaticRelaxation);
  const double normalized = diagnostic.residual / diagnostic.residual_scale;
  if (!diagnostic.converged || !cfd_ancf::finite(state) || !std::isfinite(normalized))
    throw std::runtime_error("E_STATIC_STATE_REGRESSION_MISMATCH");

  std::vector<double> internal;
  Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  const auto free_modal = free_y_dof(model);
  const Matrix mass_ff = select_rows_cols(state.mass, free_modal);
  const Matrix tangent_ff = select_rows_cols(tangent, free_modal);

  const double prestretch = state.q[6u * ElementsForCase + 2u] - model.length_m;
  double balance_norm = 0.0;
  for (std::size_t i = 0; i < internal.size(); ++i) {
    const double balance = internal[i] - base_load[i];
    balance_norm = (std::max)(balance_norm, std::abs(balance));
  }
  const double fixed_error = max_constraint_error(state);

  write_vector(output_dir + "/q_static.txt", state.q);
  write_vector(output_dir + "/base_load.txt", base_load);
  write_matrix(output_dir + "/M_full.txt", state.mass);
  write_matrix(output_dir + "/M_ff.txt", mass_ff);
  write_matrix(output_dir + "/K_full.txt", tangent);
  write_matrix(output_dir + "/K_ff.txt", tangent_ff);
  write_indices(output_dir + "/free_dof.txt", free_modal);
  write_static_json(output_dir + "/static.json", diagnostic, state, model, fixed_error,
                    balance_norm, prestretch);
  std::ofstream meta(output_dir + "/setup_stdout.txt", std::ios::binary | std::ios::trunc);
  if (!meta) throw std::runtime_error("cannot write setup stdout");
  meta << std::setprecision(17)
       << "status PASS\n"
       << "q_size " << state.q.size() << "\n"
       << "free_modal_count " << free_modal.size() << "\n"
       << "static_converged " << (diagnostic.converged ? 1 : 0) << "\n"
       << "static_iterations " << diagnostic.iterations << "\n"
       << "static_residual " << diagnostic.residual << "\n"
       << "residual_scale " << diagnostic.residual_scale << "\n"
       << "normalized_residual " << normalized << "\n"
       << "max_fixed_error " << fixed_error << "\n"
       << "balance_norm_inf_over_all_dofs " << balance_norm << "\n"
       << "prestretch_delta_m " << prestretch << "\n"
       << "zero_damping alpha 0 beta 0\n";
}

void write_history_row(std::ofstream& out, std::size_t step, const cfd_ancf::State& state,
                       const cfd_ancf::StepDiagnostics& d, double qstatic_measurement,
                       bool converged, double constraint_error, bool finite_state) {
  const double normalized = d.residual_scale > 0.0 ? d.residual / d.residual_scale : 0.0;
  out << std::setprecision(17) << step << ',' << state.time_s << ','
      << state.q[43u] - qstatic_measurement << ',' << state.qdot[43u] << ','
      << (converged ? 1 : 0) << ',' << d.iterations << ',' << d.residual << ','
      << d.residual_scale << ',' << normalized << ',' << constraint_error << ','
      << (finite_state ? 1 : 0) << '\n';
}

void run_dynamic(const std::string& setup_dir, const std::string& phi_path, double dt,
                 std::size_t expected_steps, const std::string& history_path,
                 const std::string& diagnostic_path, const std::string& q0_path,
                 const std::string& qdot0_path, const std::string& qddot0_path) {
  const cfd_ancf::Model base_model = make_model();
  cfd_ancf::Model model = base_model;
  model.dt_s = dt;
  const std::vector<double> q_static = read_vector(setup_dir + "/q_static.txt");
  const std::vector<double> base_load = read_vector(setup_dir + "/base_load.txt");
  const std::vector<double> phi = read_vector(phi_path);
  if (q_static.size() != model.ndof() || base_load.size() != model.ndof() ||
      phi.size() != model.ndof()) throw std::runtime_error("E_INITIAL_STATE_INVALID");

  cfd_ancf::State state = cfd_ancf::make_reference_state(model);
  state.q = q_static;
  for (std::size_t i = 0; i < state.q.size(); ++i) state.q[i] += PerturbationAmplitude * phi[i];
  state.qdot.assign(model.ndof(), 0.0);
  state.base_load = base_load;

  std::vector<double> internal;
  Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
  std::vector<double> rhs(model.ndof(), 0.0);
  for (std::size_t i = 0; i < model.ndof(); ++i) rhs[i] = base_load[i] - internal[i];
  const std::vector<std::size_t> free_dynamic = dynamic_free_dof(model.ndof());
  const Matrix mass_free = select_rows_cols(state.mass, free_dynamic);
  const std::vector<double> acceleration_free = solve_dense(mass_free, select_vector(rhs, free_dynamic));
  state.qddot.assign(model.ndof(), 0.0);
  for (std::size_t i = 0; i < free_dynamic.size(); ++i)
    state.qddot[free_dynamic[i]] = acceleration_free[i];

  write_vector(q0_path, state.q);
  write_vector(qdot0_path, state.qdot);
  write_vector(qddot0_path, state.qddot);

  const std::string temporary_history = history_path + ".tmp";
  std::ofstream history(temporary_history, std::ios::binary | std::ios::trunc);
  if (!history) throw std::runtime_error("E_EVIDENCE_SERIALIZATION_FAIL");
  history << "step,time,displacement_rel_qstatic,velocity,converged,iterations,residual,residual_scale,normalized_residual,constraint_error,finite\n";
  cfd_ancf::StepDiagnostics initial;
  initial.residual_scale = 1.0;
  write_history_row(history, 0u, state, initial, q_static[43u], true,
                    max_constraint_error(state), cfd_ancf::finite(state));
  bool all_ok = true;
  std::string failure;
  std::vector<double> zero_slice_force(model.slices * 3u, 0.0);
  for (std::size_t step = 1; step <= expected_steps; ++step) {
    cfd_ancf::StepDiagnostics diagnostic;
    bool finite_state = true;
    bool converged = false;
    double constraint_error = 0.0;
    try {
      diagnostic = cfd_ancf::advance(state, model, zero_slice_force);
      finite_state = cfd_ancf::finite(state);
      converged = diagnostic.converged;
      constraint_error = max_constraint_error(state);
    } catch (const std::exception& error) {
      failure = error.what();
      finite_state = false;
      diagnostic.failure_reason = failure;
    }
    write_history_row(history, step, state, diagnostic, q_static[43u], converged,
                      constraint_error, finite_state);
    if (!converged || !finite_state || constraint_error > 1.0e-12) {
      all_ok = false;
      if (failure.empty()) failure = !finite_state ? "E_NONFINITE_RESULT" :
          (!converged ? "E_DYNAMIC_STEP_FAIL" : "E_CONSTRAINT_FAIL");
      break;
    }
  }
  history.flush();
  history.close();
  if (fs::exists(history_path)) fs::remove(history_path);
  fs::rename(temporary_history, history_path);

  std::ofstream diagnostic_out(diagnostic_path + ".tmp", std::ios::binary | std::ios::trunc);
  if (!diagnostic_out) throw std::runtime_error("E_EVIDENCE_SERIALIZATION_FAIL");
  diagnostic_out << std::setprecision(17)
                 << "{\"dt\":" << dt
                 << ",\"expected_steps\":" << expected_steps
                 << ",\"completed_steps\":" << (all_ok ? expected_steps : 0u)
                 << ",\"all_steps_converged\":" << (all_ok ? "true" : "false")
                 << ",\"failure\":\"" << failure << "\""
                 << ",\"q0_written\":true,\"qdot0_written\":true,\"qddot0_written\":true"
                 << ",\"zero_damping\":true}\n";
  diagnostic_out.flush();
  diagnostic_out.close();
  if (fs::exists(diagnostic_path)) fs::remove(diagnostic_path);
  fs::rename(diagnostic_path + ".tmp", diagnostic_path);
  std::cout << std::setprecision(17) << "status " << (all_ok ? "PASS" : "FAIL")
            << " dt " << dt << " expected_steps " << expected_steps
            << " completed_steps " << (all_ok ? expected_steps : 0u)
            << " failure " << failure << '\n';
  if (!all_ok) throw std::runtime_error(failure.empty() ? "E_DYNAMIC_STEP_FAIL" : failure);
}

}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc == 3 && std::string(argv[1]) == "setup") {
      run_setup(argv[2]);
      return 0;
    }
    if (argc == 10 && std::string(argv[1]) == "run") {
      const double dt = std::stod(argv[4]);
      const std::size_t steps = static_cast<std::size_t>(std::stoull(argv[5]));
      run_dynamic(argv[2], argv[3], dt, steps, argv[6], argv[7], argv[8], argv[9],
                  std::string(argv[6]) + ".qddot0.txt");
      return 0;
    }
    std::cerr << "usage: replacement setup <dir> | replacement run <setup> <phi> <dt> <steps> <history> <diagnostic> <q0> <qdot0>\n";
    return 2;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
