#include "../cpp_worker_persistent_ipc_v1/ancf_kernel.hpp"
#include "physics_ownership.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#include <bcrypt.h>
#endif

namespace {
constexpr std::array<char, 8> MAGIC{'C', 'F', 'D', 'A', 'N', 'C', 'F', '1'};
constexpr std::uint32_t SCHEMA = 1;
constexpr std::uint32_t PROTOCOL = 1;
constexpr std::uint32_t STEP_REQUEST = 5;
constexpr std::uint32_t STEP_RESPONSE = 6;
constexpr std::size_t ID_RUN = 64;
constexpr std::size_t ID_CASE = 64;
constexpr std::size_t ID_ENDPOINT = 32;

template <class T>
bool take(const std::vector<char>& payload, std::size_t& offset, T& value) {
  if (offset + sizeof(T) > payload.size()) return false;
  std::memcpy(&value, payload.data() + offset, sizeof(T));
  offset += sizeof(T);
  return true;
}

void append_bytes(std::vector<char>& output, const void* data, std::size_t size) {
  const auto* begin = static_cast<const char*>(data);
  output.insert(output.end(), begin, begin + size);
}

template <class T>
void append(std::vector<char>& output, const T& value) { append_bytes(output, &value, sizeof(T)); }

bool read_bytes(std::istream& input, char* data, std::size_t size) {
  return static_cast<bool>(input.read(data, static_cast<std::streamsize>(size)));
}

bool valid_c_string(const char* value, std::size_t size) {
  for (std::size_t index = 0; index < size; ++index) {
    if (value[index] == '\0') return index > 0;
    if (static_cast<unsigned char>(value[index]) < 0x20) return false;
  }
  return false;
}

std::string string_value(const char* value, std::size_t size) {
  std::size_t length = 0;
  while (length < size && value[length] != '\0') ++length;
  return std::string(value, length);
}

bool finite_values(const std::vector<double>& values) {
  for (double value : values) if (!std::isfinite(value)) return false;
  return true;
}
bool little_endian() {
  const std::uint16_t marker = 1;
  return *reinterpret_cast<const std::uint8_t*>(&marker) == 1;
}

bool close_vector(const std::vector<double>& lhs, const std::vector<double>& rhs,
                 double abs_tolerance, double rel_tolerance) {
  if (lhs.size() != rhs.size()) return false;
  for (std::size_t index = 0; index < lhs.size(); ++index) {
    const double scale = (std::max)(1.0, (std::max)(std::abs(lhs[index]), std::abs(rhs[index])));
    if (std::abs(lhs[index] - rhs[index]) >
        (std::max)(abs_tolerance, rel_tolerance * scale)) return false;
  }
  return true;
}

bool sha256_bytes(const std::vector<unsigned char>& bytes, std::array<unsigned char, 32>& digest) {
#ifdef _WIN32
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  DWORD object_length = 0;
  DWORD bytes_written = 0;
  if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0) return false;
  bool ok = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                              reinterpret_cast<PUCHAR>(&object_length), sizeof(object_length),
                              &bytes_written, 0) == 0;
  std::vector<unsigned char> object(object_length);
  if (ok) ok = BCryptCreateHash(algorithm, &hash, object.data(), object_length, nullptr, 0, 0) == 0;
  if (ok && !bytes.empty()) ok = BCryptHashData(hash, const_cast<PUCHAR>(bytes.data()),
                                                static_cast<ULONG>(bytes.size()), 0) == 0;
  if (ok) ok = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) == 0;
  if (hash != nullptr) BCryptDestroyHash(hash);
  if (algorithm != nullptr) BCryptCloseAlgorithmProvider(algorithm, 0);
  return ok;
#else
  (void)bytes; (void)digest;
  return false;
#endif
}

bool append_array_hash(const std::vector<double>& values, std::array<unsigned char, 32>& digest) {
  std::vector<unsigned char> bytes(values.size() * sizeof(double));
  if (!bytes.empty()) std::memcpy(bytes.data(), values.data(), bytes.size());
  return sha256_bytes(bytes, digest);
}

bool append_profile(std::int32_t global_step, std::uint32_t sequence,
                    const cfd_ancf::StepDiagnostics& diagnostics) {
  std::string path_value;
#ifdef _WIN32
  char* raw_path = nullptr;
  std::size_t raw_size = 0;
  if (_dupenv_s(&raw_path, &raw_size, "CFD_ANCF_PROFILE_PATH") != 0) return false;
  if (raw_path != nullptr) {
    path_value.assign(raw_path);
    std::free(raw_path);
  }
#else
  const char* raw_path = std::getenv("CFD_ANCF_PROFILE_PATH");
  if (raw_path != nullptr) path_value.assign(raw_path);
#endif
  if (path_value.empty()) return true;
  std::ofstream output(path_value, std::ios::app);
  if (!output) return false;
  output.setf(std::ios::fmtflags(0), std::ios::floatfield);
  output << "{\"global_step\":" << global_step
         << ",\"sequence\":" << sequence
         << ",\"matrix_assembly_s\":" << diagnostics.matrix_assembly_s
         << ",\"linear_solve_s\":" << diagnostics.linear_solve_s
         << ",\"state_update_s\":" << diagnostics.state_update_s
         << ",\"predictor_s\":" << diagnostics.predictor_s
          << ",\"external_mapping_s\":" << diagnostics.external_mapping_s
          << ",\"newton_iterations\":" << diagnostics.iterations << "}\n";
  return static_cast<bool>(output);
}

int process_step(const std::vector<char>& payload, std::vector<char>& response,
                 std::uint32_t expected_sequence, std::string& expected_run,
                 std::string& expected_case, std::int32_t& expected_global_step,
                 std::int32_t& expected_bridge_step, std::uint64_t& expected_tick,
                 double& expected_time_s, double& expected_dt_s,
                 std::array<unsigned char, 32>& expected_model_digest,
                 std::unordered_set<std::uint64_t>& seen_request_ids,
                 std::unordered_set<std::uint64_t>& seen_transaction_ids) {
  std::size_t offset = 0;
  std::uint32_t schema = 0, protocol = 0, sequence = 0;
  std::int32_t global_step = 0, bridge_step = 0;
  std::uint64_t integer_tick = 0, request_id = 0, transaction_id = 0;
  double time_s = 0.0, dt_s = 0.0;
  std::int32_t n = 0, elements = 0, slices = 0, gauss_order = 0, max_newton = 0;
  if (!take(payload, offset, schema) || !take(payload, offset, protocol) || !take(payload, offset, sequence) ||
      !take(payload, offset, global_step) || !take(payload, offset, bridge_step) || !take(payload, offset, integer_tick) ||
      !take(payload, offset, time_s) || !take(payload, offset, dt_s) || !take(payload, offset, n) ||
      !take(payload, offset, elements) || !take(payload, offset, slices) || !take(payload, offset, gauss_order) ||
      !take(payload, offset, max_newton) || !take(payload, offset, request_id) || !take(payload, offset, transaction_id)) {
    return 2;
  }
  if (schema != SCHEMA || protocol != PROTOCOL || sequence == 0 || n <= 0 || n > 100000 ||
      elements < 2 || elements > 10000 || slices < 1 || slices > 1000 ||
      gauss_order != 3 && gauss_order != 5 || max_newton <= 0 || dt_s <= 0.0 || !std::isfinite(time_s) ||
      !std::isfinite(dt_s) || n != 6 * (elements + 1)) return 3;

  if (time_s < 0.0 || time_s > 1.0e9) return 3;
  const auto request_tick = static_cast<std::uint64_t>(std::llround(time_s * 1.0e9));
  if (global_step <= 0 || bridge_step <= 0 || integer_tick != request_tick || time_s < dt_s ||
      (expected_sequence == 1 && bridge_step != 1)) return 3;
  if (request_id == 0 || transaction_id == 0 || seen_request_ids.count(request_id) != 0 ||
      seen_transaction_ids.count(transaction_id) != 0) return 18;

  const std::size_t model_start = offset;
  cfd_ancf::Model model;
  if (!take(payload, offset, model.length_m) || !take(payload, offset, model.diameter_m) ||
      !take(payload, offset, model.inner_diameter_m) || !take(payload, offset, model.top_tension_N) ||
      !take(payload, offset, model.youngs_modulus_Pa) || !take(payload, offset, model.material_density) ||
      !take(payload, offset, model.fluid_density) || !take(payload, offset, model.gravity) ||
      !take(payload, offset, model.beta) || !take(payload, offset, model.gamma) ||
      !take(payload, offset, model.newton_tolerance) || !take(payload, offset, model.damping_alpha) ||
      !take(payload, offset, model.damping_beta)) return 4;
  std::int32_t model_gauss_order = 0, model_max_newton = 0;
  if (!take(payload, offset, model_gauss_order) || !take(payload, offset, model_max_newton) ||
      model_gauss_order != gauss_order || model_max_newton != max_newton) return 4;
  model.gauss_order = static_cast<std::size_t>(model_gauss_order);
  model.max_newton = static_cast<std::size_t>(model_max_newton);
  model.slice_positions_m.resize(static_cast<std::size_t>(slices));
  for (double& position : model.slice_positions_m) if (!take(payload, offset, position)) return 4;
  const std::size_t model_end = offset;
  model.elements = static_cast<std::size_t>(elements);
  model.slices = static_cast<std::size_t>(slices);
  model.dt_s = dt_s;
  if (model.damping_alpha != 0.0 || model.damping_beta != 0.0) return 4;
  std::int32_t base_n = 0, force_n = 0, mass_n = 0;
  if (!take(payload, offset, base_n) || !take(payload, offset, force_n) ||
      base_n != n || force_n != 3 * slices) return 5;
  // A third size is present only for the extended source-state mass layout.
  // Legacy frames place the first four run-id bytes here, so rewind unless it
  // is an explicitly valid mass dimension.
  const std::size_t after_legacy_sizes = offset;
  std::int32_t candidate_mass_n = 0;
  if (take(payload, offset, candidate_mass_n) && (candidate_mass_n == 0 || candidate_mass_n == n)) {
    mass_n = candidate_mass_n;
  } else {
    offset = after_legacy_sizes;
  }

  char run_id[ID_RUN]{}, case_id[ID_CASE]{}, producer[ID_ENDPOINT]{}, consumer[ID_ENDPOINT]{};
  if (offset + ID_RUN + ID_CASE + ID_ENDPOINT + ID_ENDPOINT + 32 > payload.size()) return 6;
  std::memcpy(run_id, payload.data() + offset, ID_RUN); offset += ID_RUN;
  std::memcpy(case_id, payload.data() + offset, ID_CASE); offset += ID_CASE;
  std::memcpy(producer, payload.data() + offset, ID_ENDPOINT); offset += ID_ENDPOINT;
  std::memcpy(consumer, payload.data() + offset, ID_ENDPOINT); offset += ID_ENDPOINT;
  std::array<unsigned char, 32> request_digest{};
  std::memcpy(request_digest.data(), payload.data() + offset, request_digest.size()); offset += request_digest.size();
  if (!valid_c_string(run_id, ID_RUN) || !valid_c_string(case_id, ID_CASE) ||
      !valid_c_string(producer, ID_ENDPOINT) || !valid_c_string(consumer, ID_ENDPOINT)) return 7;
  if (sequence != expected_sequence) return 13;
  const std::string run_value = string_value(run_id, ID_RUN);
  const std::string case_value = string_value(case_id, ID_CASE);
  if (expected_run.empty()) {
    expected_run = run_value;
    expected_case = case_value;
  } else if (run_value != expected_run || case_value != expected_case) {
    return 14;
  }
  seen_request_ids.insert(request_id);
  seen_transaction_ids.insert(transaction_id);

  std::vector<unsigned char> model_bytes(
      payload.begin() + static_cast<std::ptrdiff_t>(model_start),
      payload.begin() + static_cast<std::ptrdiff_t>(model_end));
  std::array<unsigned char, 32> model_digest{};
  if (!sha256_bytes(model_bytes, model_digest)) return 15;
  if (expected_sequence == 1) {
    expected_global_step = global_step;
    expected_bridge_step = bridge_step;
    expected_tick = integer_tick;
    expected_time_s = time_s;
    expected_dt_s = dt_s;
    expected_model_digest = model_digest;
  } else {
    const double expected_next_time = expected_time_s + expected_dt_s;
    if (global_step != expected_global_step + 1 || bridge_step != expected_bridge_step + 1 ||
        integer_tick != static_cast<std::uint64_t>(std::llround(time_s * 1.0e9)) ||
        std::abs(time_s - expected_next_time) > 1.0e-12 ||
        std::abs(dt_s - expected_dt_s) > 1.0e-15 || model_digest != expected_model_digest) {
      return 16;
    }
    expected_global_step = global_step;
    expected_bridge_step = bridge_step;
    expected_tick = integer_tick;
    expected_time_s = time_s;
  }

  // The ownership worker is the production mass-matrix owner. External mass
  // matrices belong to the legacy protocol and are rejected here.
  if (mass_n != 0) return 17;
  const std::size_t mass_count = 0u;
  const std::size_t array_count = static_cast<std::size_t>(4 * n) + mass_count + static_cast<std::size_t>(force_n);
  if (offset + array_count * sizeof(double) != payload.size()) return 8;
  std::vector<double> input(array_count);
  std::memcpy(input.data(), payload.data() + offset, input.size() * sizeof(double));
  std::vector<unsigned char> request_hash_bytes;
  request_hash_bytes.insert(request_hash_bytes.end(), payload.begin() + static_cast<std::ptrdiff_t>(model_start),
                            payload.begin() + static_cast<std::ptrdiff_t>(model_end));
  request_hash_bytes.insert(request_hash_bytes.end(), reinterpret_cast<unsigned char*>(input.data()),
                            reinterpret_cast<unsigned char*>(input.data()) + input.size() * sizeof(double));
  std::array<unsigned char, 32> calculated_request_digest{};
  if (!sha256_bytes(request_hash_bytes, calculated_request_digest) || calculated_request_digest != request_digest ||
      !finite_values(input)) return 9;

  const std::vector<double> q(input.begin(), input.begin() + n);
  const std::vector<double> qdot(input.begin() + n, input.begin() + 2 * n);
  const std::vector<double> qddot(input.begin() + 2 * n, input.begin() + 3 * n);
  const std::vector<double> supplied_base_load(input.begin() + 3 * n, input.begin() + 4 * n);
  const auto owned_base = cfd_ancf::physics_ownership::assemble_base_load(model);
  if (!cfd_ancf::physics_ownership::finite(supplied_base_load)) return 9;
  // The fourth request vector is the non-zero MATLAB golden base-load
  // reference. It is never an additional runtime load. Applying it again
  // would double-count gravity, buoyancy, and top tension.
  if (!close_vector(supplied_base_load, owned_base.base, 1.0e-8, 1.0e-12)) return 18;
  const std::vector<double>& base_load = owned_base.base;
  std::size_t input_offset = 4 * n;
  const std::vector<double> predictor = [&]() {
    std::vector<double> value(q.size());
    for (std::size_t index = 0; index < q.size(); ++index) {
      value[index] = q[index] + dt_s * qdot[index] + dt_s * dt_s * (0.5 - model.beta) * qddot[index];
    }
    return value;
  }();

  cfd_ancf::State state = cfd_ancf::make_reference_state(model);
  state.mass = cfd_ancf::physics_ownership::assemble_mass_matrix(model);
  cfd_ancf::symmetrize_mass(state);
  const std::vector<double> slice_force(input.begin() + static_cast<std::ptrdiff_t>(input_offset), input.end());
  state.q = q; state.qdot = qdot; state.qddot = qddot; state.base_load = base_load;
  if (time_s < dt_s) return 10;
  state.time_s = time_s - dt_s; state.step = static_cast<std::size_t>(global_step - 1);
  std::vector<double> internal_before; cfd_ancf::Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal_before, tangent);
  const auto cfd_load = cfd_ancf::physics_ownership::assemble_cfd_load(
      model, slice_force, cfd_ancf::physics_ownership::ForceRepresentation::integrated_N);
  const std::vector<double>& cfd_external = cfd_load.generalized_force;
  std::vector<double> generalized = base_load;
  for (std::size_t index = 0; index < generalized.size(); ++index) generalized[index] += cfd_external[index];
  cfd_ancf::StepDiagnostics diagnostics;
  try {
    diagnostics = cfd_ancf::advance(state, model, slice_force);
  } catch (const std::exception&) {
    return 12;
  }
  if (!append_profile(global_step, sequence, diagnostics)) return 19;
  std::vector<double> internal_after; cfd_ancf::internal_force_tangent(state.q, model, internal_after, tangent);
  const std::vector<double> corrector = state.q;
  const std::vector<double> output_arrays = [&]() {
    std::vector<double> value; value.reserve(8 * q.size());
    const std::array<const std::vector<double>*, 8> vectors{
        &state.q, &state.qdot, &state.qddot, &internal_after,
        // MATLAB's current dual-run schema calls this field external_force
        // but stores total Qext. Preserve that established semantic here.
        &generalized, &generalized, &predictor, &corrector};
    for (const auto* vector : vectors) {
      value.insert(value.end(), vector->begin(), vector->end());
    }
    return value;
  }();
  if (!cfd_ancf::finite(state) || !finite_values(output_arrays) || !std::isfinite(diagnostics.residual)) return 10;
  std::array<unsigned char, 32> output_digest{};
  if (!append_array_hash(output_arrays, output_digest)) return 11;

  const std::uint32_t ack = 1;
  append(response, schema); append(response, protocol); append(response, sequence); append(response, global_step);
  append(response, bridge_step); append(response, integer_tick); append(response, time_s); append(response, n);
  const std::int32_t return_code = 0;
  const std::int32_t iterations = static_cast<std::int32_t>(diagnostics.iterations);
  append(response, return_code); append(response, iterations);
  append(response, diagnostics.residual); append(response, transaction_id); append(response, request_id); append(response, ack);
  response.insert(response.end(), run_id, run_id + ID_RUN);
  response.insert(response.end(), case_id, case_id + ID_CASE);
  response.insert(response.end(), consumer, consumer + ID_ENDPOINT);
  response.insert(response.end(), producer, producer + ID_ENDPOINT);
  response.insert(response.end(), reinterpret_cast<const char*>(output_digest.data()),
                  reinterpret_cast<const char*>(output_digest.data()) + output_digest.size());
  for (double value : output_arrays) append(response, value);
  const std::uint64_t checkpoint_step = static_cast<std::uint64_t>(state.step);
  const std::uint32_t finite_audit = 1;
  append(response, checkpoint_step); append(response, time_s); append(response, integer_tick); append(response, finite_audit);
  return 0;
}
}

int main() {
  if (!little_endian()) return 21;
#ifdef _WIN32
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  std::uint32_t last_sequence = 0;
  std::string expected_run;
  std::string expected_case;
  std::int32_t expected_global_step = 0;
  std::int32_t expected_bridge_step = 0;
  std::uint64_t expected_tick = 0;
  double expected_time_s = 0.0;
  double expected_dt_s = 0.0;
  std::array<unsigned char, 32> expected_model_digest{};
  std::unordered_set<std::uint64_t> seen_request_ids, seen_transaction_ids;
  while (true) {
    std::array<char, 8> magic{}; std::uint32_t length = 0, message_type = 0;
    if (!read_bytes(std::cin, magic.data(), magic.size())) return 0;
    if (!read_bytes(std::cin, reinterpret_cast<char*>(&length), sizeof(length)) ||
        !read_bytes(std::cin, reinterpret_cast<char*>(&message_type), sizeof(message_type)) || magic != MAGIC) return 2;
    if (length > 64u * 1024u * 1024u) return 3;
    if (message_type == 3) { if (length != 0) return 4; return 0; }
    if (message_type == 4) { if (length != 0) return 4; continue; }
    if (message_type != STEP_REQUEST) return 5;
    std::vector<char> payload(length);
    if (!read_bytes(std::cin, payload.data(), payload.size())) return 6;
    std::vector<char> response;
    int result = 0;
    try {
      result = process_step(payload, response, last_sequence + 1, expected_run, expected_case,
                            expected_global_step, expected_bridge_step, expected_tick,
                            expected_time_s, expected_dt_s, expected_model_digest,
                            seen_request_ids, seen_transaction_ids);
    } catch (const std::exception& error) {
      std::cerr << "ownership worker exception: " << error.what() << '\n';
      return 20;
    }
    if (result != 0) return result;
    std::uint32_t response_length = static_cast<std::uint32_t>(response.size());
    std::cout.write(MAGIC.data(), MAGIC.size());
    std::cout.write(reinterpret_cast<const char*>(&response_length), sizeof(response_length));
    std::cout.write(reinterpret_cast<const char*>(&STEP_RESPONSE), sizeof(STEP_RESPONSE));
    std::cout.write(response.data(), static_cast<std::streamsize>(response.size()));
    std::cout.flush();
    ++last_sequence;
  }
}
