#define main ancf_prestretched_modal_current_line_validation_v1_original_main
#include "ancf_prestretched_modal_current_line_validation_v1.cpp"
#undef main

#include <array>
#include <cstdint>
#include <filesystem>
#include <sstream>

namespace {

struct Sha256 {
  std::array<std::uint32_t, 8> state = {
      0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
      0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
  std::array<unsigned char, 64> block{};
  std::size_t used = 0;
  std::uint64_t bits = 0;

  static std::uint32_t rotr(std::uint32_t value, unsigned count) {
    return (value >> count) | (value << (32u - count));
  }

  void transform() {
    static constexpr std::uint32_t k[64] = {
        0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu,
        0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u,
        0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u,
        0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
        0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u,
        0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u,
        0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
        0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
        0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u,
        0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u, 0x1e376c08u,
        0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu,
        0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
        0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};
    std::uint32_t w[64]{};
    for (unsigned i = 0; i < 16; ++i)
      w[i] = (static_cast<std::uint32_t>(block[4 * i]) << 24u) |
             (static_cast<std::uint32_t>(block[4 * i + 1]) << 16u) |
             (static_cast<std::uint32_t>(block[4 * i + 2]) << 8u) |
             static_cast<std::uint32_t>(block[4 * i + 3]);
    for (unsigned i = 16; i < 64; ++i) {
      const std::uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3u);
      const std::uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10u);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    std::uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
    std::uint32_t e = state[4], f = state[5], g = state[6], h = state[7];
    for (unsigned i = 0; i < 64; ++i) {
      const std::uint32_t s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const std::uint32_t choose = (e & f) ^ ((~e) & g);
      const std::uint32_t t1 = h + s1 + choose + k[i] + w[i];
      const std::uint32_t s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t t2 = s0 + majority;
      h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
  }

  void update(const std::string& text) {
    for (unsigned char value : text) {
      block[used++] = value;
      bits += 8u;
      if (used == block.size()) { transform(); used = 0; }
    }
  }

  std::string finish() {
    const std::size_t original_used = used;
    block[used++] = 0x80u;
    while (used != 56u) {
      if (used == 64u) { transform(); used = 0; }
      block[used++] = 0;
    }
    for (unsigned i = 0; i < 8; ++i)
      block[56u + i] = static_cast<unsigned char>(bits >> (56u - 8u * i));
    transform();
    (void)original_used;
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (std::uint32_t value : state) out << std::setw(8) << value;
    return out.str();
  }
};

std::string sha256_text(const std::string& text) {
  Sha256 sha;
  sha.update(text);
  return sha.finish();
}

std::string number(double value) {
  if (!std::isfinite(value)) return "null";
  std::ostringstream out;
  out << std::setprecision(17) << value;
  return out.str();
}

std::string bool_json(bool value) { return value ? "true" : "false"; }

void atomic_write(const std::string& path, const std::string& text) {
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

std::string vector_text(const std::vector<double>& values) {
  std::ostringstream out;
  out << std::setprecision(17);
  for (double value : values) out << value << '\n';
  return out.str();
}

std::string index_text(const std::vector<std::size_t>& values) {
  std::ostringstream out;
  for (std::size_t value : values) out << value << '\n';
  return out.str();
}

std::string matrix_text(const cfd_ancf::Matrix& matrix) {
  std::ostringstream out;
  out << std::setprecision(17);
  for (std::size_t row = 0; row < matrix.rows; ++row) {
    for (std::size_t col = 0; col < matrix.cols; ++col) {
      if (col != 0) out << ' ';
      out << matrix(row, col);
    }
    out << '\n';
  }
  return out.str();
}

std::string json_modes(const std::vector<double>& reference,
                       const std::vector<double>& current,
                       const std::vector<double>& absolute,
                       const std::vector<double>& relative,
                       const std::vector<double>& lambda,
                       const std::vector<double>& residual,
                       bool positive_finite) {
  std::ostringstream out;
  out << "[\n";
  for (std::size_t i = 0; i < reference.size(); ++i) {
    if (i != 0) out << ",\n";
    const bool valid = positive_finite && std::isfinite(lambda[i]) && lambda[i] > 0.0;
    const bool residual_pass = std::isfinite(residual[i]) && residual[i] <= EigenResidualTolerance;
    const bool frequency_pass = std::isfinite(relative[i]) && relative[i] <= FrequencyTolerance;
    out << "    {\"mode\": " << (i + 1)
        << ", \"lambda\": " << number(lambda[i])
        << ", \"omega_rad_s\": " << number(valid ? std::sqrt(lambda[i]) : std::numeric_limits<double>::quiet_NaN())
        << ", \"frequency_current_hz\": " << number(current[i])
        << ", \"frequency_reference_hz\": " << number(reference[i])
        << ", \"absolute_error_hz\": " << number(absolute[i])
        << ", \"relative_error\": " << number(relative[i])
        << ", \"eigenpair_residual\": " << number(residual[i])
        << ", \"positive_finite_gate\": " << bool_json(valid)
        << ", \"eigenpair_residual_gate\": " << bool_json(residual_pass)
        << ", \"frequency_gate\": " << bool_json(frequency_pass) << "}";
  }
  out << "\n  ]";
  return out.str();
}

std::string static_json(const cfd_ancf::StepDiagnostics& diag,
                        double normalized,
                        double fixed_error,
                        double root_x, double root_y, double root_z,
                        double top_x, double top_y,
                        double balance_x, double balance_y, double balance_z,
                        double balance_norm, double top_z, double delta) {
  std::ostringstream out;
  out << "{\n"
      << "  \"converged\": " << bool_json(diag.converged) << ",\n"
      << "  \"iterations\": " << diag.iterations << ",\n"
      << "  \"initial_residual\": " << number(diag.initial_residual) << ",\n"
      << "  \"residual\": " << number(diag.residual) << ",\n"
      << "  \"residual_scale\": " << number(diag.residual_scale) << ",\n"
      << "  \"normalized_residual\": " << number(normalized) << ",\n"
      << "  \"failure_reason\": \"" << (diag.failure_reason.empty() ? "none" : diag.failure_reason) << "\",\n"
      << "  \"max_fixed_error\": " << number(fixed_error) << ",\n"
      << "  \"root_reaction_xyz\": [" << number(root_x) << ", " << number(root_y) << ", " << number(root_z) << "],\n"
      << "  \"top_reaction_xy\": [" << number(top_x) << ", " << number(top_y) << "],\n"
      << "  \"global_balance_xyz\": [" << number(balance_x) << ", " << number(balance_y) << ", " << number(balance_z) << "],\n"
      << "  \"global_balance_norm\": " << number(balance_norm) << ",\n"
      << "  \"prestretch_top_z_m\": " << number(top_z) << ",\n"
      << "  \"prestretch_delta_m\": " << number(delta) << "\n"
      << "}\n";
  return out.str();
}

std::string matrix_identity_json(const std::vector<double>& q,
                                 const cfd_ancf::Matrix& mass,
                                 const cfd_ancf::Matrix& mass_ff,
                                 const cfd_ancf::Matrix& tangent,
                                 const cfd_ancf::Matrix& tangent_ff,
                                 const std::vector<std::size_t>& free) {
  const std::string q_text = vector_text(q);
  const std::string m_text = matrix_text(mass);
  const std::string mff_text = matrix_text(mass_ff);
  const std::string k_text = matrix_text(tangent);
  const std::string kff_text = matrix_text(tangent_ff);
  const std::string free_text = index_text(free);
  std::ostringstream out;
  out << "{\n"
      << "  \"q\": {\"count\": " << q.size() << ", \"sha256\": \"" << sha256_text(q_text) << "\"},\n"
      << "  \"M_full\": {\"rows\": " << mass.rows << ", \"cols\": " << mass.cols
      << ", \"frobenius\": " << number(frobenius(mass)) << ", \"symmetry\": " << number(symmetry_error(mass))
      << ", \"sha256\": \"" << sha256_text(m_text) << "\"},\n"
      << "  \"M_ff\": {\"rows\": " << mass_ff.rows << ", \"cols\": " << mass_ff.cols
      << ", \"frobenius\": " << number(frobenius(mass_ff)) << ", \"symmetry\": " << number(symmetry_error(mass_ff))
      << ", \"sha256\": \"" << sha256_text(mff_text) << "\"},\n"
      << "  \"K_full\": {\"rows\": " << tangent.rows << ", \"cols\": " << tangent.cols
      << ", \"frobenius\": " << number(frobenius(tangent)) << ", \"symmetry\": " << number(symmetry_error(tangent))
      << ", \"sha256\": \"" << sha256_text(k_text) << "\"},\n"
      << "  \"K_ff\": {\"rows\": " << tangent_ff.rows << ", \"cols\": " << tangent_ff.cols
      << ", \"frobenius\": " << number(frobenius(tangent_ff)) << ", \"symmetry\": " << number(symmetry_error(tangent_ff))
      << ", \"sha256\": \"" << sha256_text(kff_text) << "\"},\n"
      << "  \"free_dof\": {\"count\": " << free.size() << ", \"sha256\": \"" << sha256_text(free_text) << "\"}\n"
      << "}\n";
  return out.str();
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 13) {
    std::cerr << "usage: modal_v1_1 <result> <modes> <static> <matrix> <snapshot> <reconstruction> <q> <Mfull> <Mff> <Kfull> <Kff> <free>\n";
    return 2;
  }
  try {
    const cfd_ancf::Model model = make_model();
    cfd_ancf::State state = cfd_ancf::make_reference_state(model);
    const std::vector<double> base_load = cfd_ancf::static_base_load(model);
    const cfd_ancf::StepDiagnostics static_diag =
        cfd_ancf::static_equilibrium(state, model, base_load, LoadSteps, StaticRelaxation);
    const double normalized_static_residual = static_diag.residual / static_diag.residual_scale;

    std::vector<double> internal;
    cfd_ancf::Matrix tangent;
    cfd_ancf::internal_force_tangent(state.q, model, internal, tangent);
    std::vector<double> reaction(internal.size(), 0.0);
    for (std::size_t i = 0; i < reaction.size(); ++i) reaction[i] = internal[i] - base_load[i];
    const std::size_t top = 6u * Elements;
    const double root_x = reaction[0], root_y = reaction[1], root_z = reaction[2];
    const double top_x = reaction[top], top_y = reaction[top + 1u];
    double external_x = 0.0, external_y = 0.0, external_z = 0.0;
    for (std::size_t node = 0; node <= Elements; ++node) {
      const std::size_t dof = 6u * node;
      external_x += base_load[dof]; external_y += base_load[dof + 1u]; external_z += base_load[dof + 2u];
    }
    const double balance_x = external_x + root_x + top_x;
    const double balance_y = external_y + root_y + top_y;
    const double balance_z = external_z + root_z;
    const double balance_norm = std::sqrt(balance_x * balance_x + balance_y * balance_y + balance_z * balance_z);
    const double top_z = state.q[top + 2u];
    const double delta = top_z - model.length_m;
    const auto free = free_y_dof(model);
    const cfd_ancf::Matrix mass = select(state.mass, free);
    const cfd_ancf::Matrix stiffness = select(tangent, free);

    const std::string q_text = vector_text(state.q);
    const std::string m_text = matrix_text(state.mass);
    const std::string mff_text = matrix_text(mass);
    const std::string k_text = matrix_text(tangent);
    const std::string kff_text = matrix_text(stiffness);
    const std::string free_text = index_text(free);
    atomic_write(argv[7], q_text);
    atomic_write(argv[8], m_text);
    atomic_write(argv[9], mff_text);
    atomic_write(argv[10], k_text);
    atomic_write(argv[11], kff_text);
    atomic_write(argv[12], free_text);
    atomic_write(argv[3], static_json(static_diag, normalized_static_residual, 0.0,
                                      root_x, root_y, root_z, top_x, top_y,
                                      balance_x, balance_y, balance_z, balance_norm, top_z, delta));
    atomic_write(argv[4], matrix_identity_json(state.q, state.mass, mass, tangent, stiffness, free));

    const cfd_ancf::Matrix lower = cholesky_lower(mass);
    const cfd_ancf::Matrix inverse = inverse_lower(lower);
    const cfd_ancf::Matrix standard = multiply(multiply(inverse, stiffness), transpose(inverse));
    const EigenSystem eigen = jacobi_symmetric(standard);
    std::vector<std::vector<double>> modes;
    std::vector<double> lambdas;
    bool positive_finite = eigen.values.size() >= Modes;
    if (positive_finite) {
      for (std::size_t column = 0; column < Modes; ++column) {
        if (!std::isfinite(eigen.values[column]) || eigen.values[column] <= 0.0) positive_finite = false;
        if (!positive_finite) break;
        std::vector<double> transformed = extract_column(eigen.vectors, column);
        std::vector<double> mode = multiply(transpose(inverse), transformed);
        const double mass_norm = std::sqrt(dot(mode, multiply(mass, mode)));
        if (!std::isfinite(mass_norm) || mass_norm <= 0.0) { positive_finite = false; break; }
        for (double& value : mode) value /= mass_norm;
        modes.push_back(mode);
        lambdas.push_back(eigen.values[column]);
      }
    }
    std::vector<double> current(Modes, std::numeric_limits<double>::quiet_NaN());
    std::vector<double> absolute(Modes, std::numeric_limits<double>::quiet_NaN());
    std::vector<double> relative(Modes, std::numeric_limits<double>::quiet_NaN());
    std::vector<double> residual(Modes, std::numeric_limits<double>::quiet_NaN());
    std::vector<double> reference(std::begin(ReferenceFrequencies), std::end(ReferenceFrequencies));
    if (positive_finite && modes.size() == Modes) {
      for (std::size_t i = 0; i < Modes; ++i) {
        current[i] = std::sqrt(lambdas[i]) / (2.0 * Pi);
        absolute[i] = std::abs(current[i] - reference[i]);
        relative[i] = absolute[i] / std::abs(reference[i]);
        const std::vector<double> left = multiply(stiffness, modes[i]);
        const std::vector<double> right = multiply(mass, modes[i]);
        std::vector<double> error(left.size());
        for (std::size_t row = 0; row < error.size(); ++row) error[row] = left[row] - lambdas[i] * right[row];
        residual[i] = norm2(error) /
            (std::max)((std::max)(norm2(left), std::abs(lambdas[i]) * norm2(right)), 1.0e-300);
      }
    }
    cfd_ancf::Matrix phi(mass.rows, Modes);
    if (modes.size() == Modes)
      for (std::size_t col = 0; col < Modes; ++col)
        for (std::size_t row = 0; row < mass.rows; ++row) phi(row, col) = modes[col][row];
    const cfd_ancf::Matrix gram = multiply(transpose(phi), multiply(mass, phi));
    double orthogonality = 0.0;
    for (std::size_t row = 0; row < Modes; ++row)
      for (std::size_t col = 0; col < Modes; ++col) {
        const double difference = gram(row, col) - (row == col ? 1.0 : 0.0);
        orthogonality += difference * difference;
      }
    orthogonality = std::sqrt(orthogonality);

    std::ostringstream modes_csv;
    modes_csv << "mode,reference_hz,current_hz,absolute_error_hz,relative_error,lambda,eigenpair_residual,positive_finite_gate,eigenpair_residual_gate,frequency_gate\n";
    modes_csv << std::setprecision(17);
    for (std::size_t i = 0; i < Modes; ++i) {
      const bool positive_gate = positive_finite && std::isfinite(lambdas[i]) && lambdas[i] > 0.0;
      const bool residual_gate = std::isfinite(residual[i]) && residual[i] <= EigenResidualTolerance;
      const bool frequency_gate = std::isfinite(relative[i]) && relative[i] <= FrequencyTolerance;
      modes_csv << (i + 1) << ',' << number(reference[i]) << ',' << number(current[i]) << ',' << number(absolute[i]) << ','
                << number(relative[i]) << ',' << number(i < lambdas.size() ? lambdas[i] : std::numeric_limits<double>::quiet_NaN())
                << ',' << number(residual[i]) << ',' << (positive_gate ? 1 : 0) << ',' << (residual_gate ? 1 : 0) << ',' << (frequency_gate ? 1 : 0) << '\n';
    }
    atomic_write(argv[2], modes_csv.str());
    std::ostringstream reconstruction;
    reconstruction << "field,value,classification\n"
                   << "reference_frequencies_hz,matlab_reference.json.modal.modes[1:6],PERSISTED_EXACT\n"
                   << "free_dof_contract,transverse_y_position_and_gradient_with_endpoint_y_positions_fixed,RECONSTRUCTED_FROM_FROZEN_SOURCE\n"
                   << "static_solver_contract,static_equilibrium(state,model,base_load,40,0.8),PERSISTED_EXACT\n"
                   << "eigensolver_contract,Cholesky_reduction_plus_deterministic_Jacobi,RECONSTRUCTED_FROM_FROZEN_SOURCE\n"
                   << "zero_damping,alpha=0;beta=0, PERSISTED_EXACT\n";
    atomic_write(argv[6], reconstruction.str());

    std::ostringstream snapshot;
    snapshot << "{\n"
             << "  \"snapshot_written_before_gates\": true,\n"
             << "  \"static\": " << static_json(static_diag, normalized_static_residual, 0.0,
                                                   root_x, root_y, root_z, top_x, top_y,
                                                   balance_x, balance_y, balance_z, balance_norm, top_z, delta)
             << ",\n  \"matrix_identity\": " << matrix_identity_json(state.q, state.mass, mass, tangent, stiffness, free)
             << ",\n  \"modes\": " << json_modes(reference, current, absolute, relative, lambdas, residual, positive_finite)
             << ",\n  \"m_orthogonality_error\": " << number(orthogonality)
             << ",\n  \"eigensolver_iteration_count\": null,\n  \"eigensolver_iteration_count_status\": \"not_exposed\"\n}\n";
    atomic_write(argv[5], snapshot.str());

    bool residual_pass = true, frequency_pass = true;
    for (std::size_t i = 0; i < Modes; ++i) {
      residual_pass = residual_pass && std::isfinite(residual[i]) && residual[i] <= EigenResidualTolerance;
      frequency_pass = frequency_pass && std::isfinite(relative[i]) && relative[i] <= FrequencyTolerance;
    }
    std::string failure;
    if (!positive_finite) failure = "D_MODAL_NONPOSITIVE_EIGENVALUE";
    else if (!residual_pass) failure = "D_EIGENPAIR_RESIDUAL_FAIL";
    else if (!std::isfinite(orthogonality) || orthogonality > MOrthogonalityTolerance) failure = "D_M_ORTHOGONALITY_FAIL";
    else if (!frequency_pass) failure = "D_MODAL_FREQUENCY_FAIL";

    const double maximum_relative = *std::max_element(relative.begin(), relative.end());
    double relative_sum = 0.0;
    for (double value : relative) relative_sum += value * value;
    const double rms_relative = std::sqrt(relative_sum / Modes);
    std::ostringstream result;
    result << "{\n"
           << "  \"validation\": \"ANCF_PRESTRETCHED_MODAL_CURRENT_LINE_VALIDATION_V1.1\",\n"
           << "  \"status\": \"" << (failure.empty() ? "PASS" : "FAIL") << "\",\n"
           << "  \"primary_failure\": " << (failure.empty() ? "null" : ("\"" + failure + "\"")) << ",\n"
           << "  \"snapshot_written_before_gates\": true,\n"
           << "  \"frequency_tolerance_relative\": 0.005,\n"
           << "  \"eigen_residual_tolerance\": 1e-9,\n"
           << "  \"m_orthogonality_tolerance\": 1e-8,\n"
           << "  \"max_relative_frequency_error\": " << number(maximum_relative) << ",\n"
           << "  \"rms_relative_frequency_error\": " << number(rms_relative) << ",\n"
           << "  \"m_orthogonality_error\": " << number(orthogonality) << ",\n"
           << "  \"eigenpair_residual_gate\": " << bool_json(residual_pass) << ",\n"
           << "  \"frequency_gate\": " << bool_json(frequency_pass) << ",\n"
           << "  \"positive_finite_gate\": " << bool_json(positive_finite) << ",\n"
           << "  \"zero_damping\": true,\n"
           << "  \"v1_status_retained\": \"FAIL:D_MODAL_FREQUENCY_FAIL\"\n"
           << "}\n";
    atomic_write(argv[1], result.str());
    std::cout << "status " << (failure.empty() ? "PASS" : "FAIL") << "\n"
              << "snapshot_written_before_gates 1\n"
              << "first_failure " << (failure.empty() ? "none" : failure) << "\n"
              << "max_relative_frequency_error " << maximum_relative
              << " rms_relative_frequency_error " << rms_relative
              << " M_orthogonality_error " << orthogonality << '\n';
    for (std::size_t i = 0; i < Modes; ++i)
      std::cout << "mode " << (i + 1) << " reference_hz " << reference[i]
                << " current_hz " << current[i] << " relative_error " << relative[i]
                << " eigenpair_residual " << residual[i] << '\n';
    return failure.empty() ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
