#include "ancf_kernel.hpp"
#include "sha256.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
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
constexpr int UNEXPECTED_EOF = 22;
constexpr int OUTPUT_WRITE_FAILURE = 23;
constexpr int BINARY_MODE_FAILURE = 24;
constexpr std::uint32_t SCHEMA = 1;
constexpr std::uint32_t PROTOCOL = 1;
constexpr std::uint32_t STEP_REQUEST = 5;
constexpr std::uint32_t STEP_RESPONSE = 6;
constexpr std::uint32_t INITIALIZE_ACK = 7;
constexpr std::size_t ID_RUN = 64;
constexpr std::size_t ID_CASE = 64;
constexpr std::size_t ID_ENDPOINT = 32;
constexpr std::size_t ID_BOUNDARY = 64;
constexpr std::int32_t EXTENDED_LAYOUT_MARKER = 0x314C5845;
constexpr char REQUEST_PRODUCER[] = "python_scheduler";
constexpr char REQUEST_CONSUMER[] = "cpp_ancf_kernel_worker";
constexpr char WORKER_ROLE[] = "cfd_ancf_kernel_worker_v1";

template <class T>
bool take(const std::vector<char>& payload, std::size_t& offset, T& value) {
  if (offset > payload.size() || sizeof(T) > payload.size() - offset) return false;
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
  bool terminated = false;
  for (std::size_t index = 0; index < size; ++index) {
    if (value[index] == '\0') {
      if (index == 0) return false;
      terminated = true;
      for (++index; index < size; ++index) if (value[index] != '\0') return false;
      break;
    }
    if (static_cast<unsigned char>(value[index]) < 0x20) return false;
  }
  return terminated;
}

bool decode_sha256_hex(const char* text, std::array<unsigned char, 32>& digest) {
  if (text == nullptr || std::strlen(text) != 64) return false;
  auto nibble = [](char value) -> int {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
  };
  for (std::size_t index = 0; index < digest.size(); ++index) {
    const int high = nibble(text[2 * index]);
    const int low = nibble(text[2 * index + 1]);
    if (high < 0 || low < 0) return false;
    digest[index] = static_cast<unsigned char>((high << 4) | low);
  }
  return true;
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
bool environment_is_one(const char* name) {
#ifdef _WIN32
  char* raw = nullptr;
  std::size_t size = 0;
  if (_dupenv_s(&raw, &size, name) != 0) return false;
  const bool enabled = raw != nullptr && std::string(raw) == "1";
  std::free(raw);
  return enabled;
#else
  const char* raw = std::getenv(name);
  return raw != nullptr && std::string(raw) == "1";
#endif
}

bool exactly_symmetric(const cfd_ancf::Matrix& matrix) {
  if (matrix.rows != matrix.cols || matrix.data.size() != matrix.rows * matrix.cols) return false;
  for (std::size_t row = 0; row < matrix.rows; ++row) {
    for (std::size_t col = row + 1; col < matrix.cols; ++col) {
      if (matrix(row, col) != matrix(col, row)) return false;
    }
  }
  return true;
}

bool next_tick(std::uint64_t previous, double dt_s, std::uint64_t& result) {
  if (!std::isfinite(dt_s) || dt_s <= 0.0) return false;
  // Match Python float multiplication followed by C++ llround, including
  // valid fractional-nanosecond deltas at the half-tick boundary.
  const double raw = dt_s * 1.0e9;
  if (!std::isfinite(raw) || raw < 0.0 ||
      raw > static_cast<double>((std::numeric_limits<long long>::max)())) return false;
  const auto delta = static_cast<std::uint64_t>(std::llround(raw));
  if (delta == 0u) return false;
  if (previous > (std::numeric_limits<std::uint64_t>::max)() - delta) return false;
  result = previous + delta;
  return true;
}

bool canonical_time_tick(double time_s, std::uint64_t& result) {
  if (!std::isfinite(time_s) || time_s < 0.0) return false;
  const double raw = time_s * 1.0e9;
  // std::llround returns signed long long; reject values outside that domain
  // before conversion instead of relying on implementation-defined behavior.
  if (!std::isfinite(raw) ||
      raw > static_cast<double>((std::numeric_limits<long long>::max)())) return false;
  const auto rounded = std::llround(raw);
  if (rounded < 0) return false;
  result = static_cast<std::uint64_t>(rounded);
  return true;
}

bool little_endian() {
  const std::uint16_t marker = 1;
  return *reinterpret_cast<const std::uint8_t*>(&marker) == 1;
}

bool append_array_hash(const std::vector<double>& values, std::array<unsigned char, 32>& digest) {
  std::vector<unsigned char> bytes(values.size() * sizeof(double));
  if (!bytes.empty()) std::memcpy(bytes.data(), values.data(), bytes.size());
  return cfd_ancf::wire::sha256_bytes(bytes, digest);
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
         << ",\"residual_scale\":" << diagnostics.residual_scale
         << ",\"newton_iterations\":" << diagnostics.iterations << "}\n";
  return static_cast<bool>(output);
}

int process_step(const std::vector<char>& payload, std::vector<char>& response,
                 std::uint32_t expected_sequence, std::string& expected_run,
                 std::string& expected_case, std::int32_t& expected_global_step,
                 std::int32_t& expected_bridge_step, std::uint64_t& expected_tick,
                 double& expected_time_s, double& expected_dt_s,
                 std::int32_t& expected_n, std::int32_t& expected_elements,
                 std::int32_t& expected_slices,
                 std::array<unsigned char, 32>& expected_model_digest,
                 int& lineage_mode,
                 std::array<unsigned char, 32>& expected_full_contract_digest,
                 const std::array<unsigned char, 32>* external_contract_digest,
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
  if (schema != SCHEMA || protocol != PROTOCOL || sequence == 0 || n <= 0 || n > static_cast<std::int32_t>(cfd_ancf::MAX_NDOF) ||
      elements < 1 || elements > 10000 || slices < 1 || slices > 1000 ||
      (gauss_order != 3 && gauss_order != 5) || max_newton <= 0 || dt_s <= 0.0 || !std::isfinite(time_s) ||
      !std::isfinite(dt_s) || n != 6 * (elements + 1)) return 3;
  if (time_s < 0.0 || time_s > 1.0e9) return 3;
  std::uint64_t request_tick = 0;
  if (!canonical_time_tick(time_s, request_tick) ||
      global_step <= 0 || bridge_step <= 0 || integer_tick != request_tick || time_s < dt_s ||
      (expected_sequence == 1 && bridge_step != 1)) return 3;
  if (request_id == 0 || transaction_id == 0 || seen_request_ids.count(request_id) != 0 ||
      seen_transaction_ids.count(transaction_id) != 0) return 18;
  constexpr std::size_t max_seen_identities = 100000;
  if (seen_request_ids.size() >= max_seen_identities ||
      seen_transaction_ids.size() >= max_seen_identities) return 19;

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
  std::int32_t mass_gauss_order = 0, fixed_count = 0;
  std::array<char, ID_BOUNDARY> boundary_id{};
  bool explicit_contract = false;
  std::int32_t layout_marker = 0;
  constexpr std::size_t extension_header = sizeof(layout_marker) + sizeof(mass_gauss_order) + sizeof(fixed_count) + ID_BOUNDARY;
  if (offset <= payload.size() && sizeof(layout_marker) <= payload.size() - offset) {
    std::memcpy(&layout_marker, payload.data() + offset, sizeof(layout_marker));
    if (layout_marker == EXTENDED_LAYOUT_MARKER &&
        (extension_header > payload.size() - offset)) return 4;
  }
  if (offset <= payload.size() && extension_header <= payload.size() - offset) {
    std::memcpy(&layout_marker, payload.data() + offset, sizeof(layout_marker));
    const bool marker_present = layout_marker == EXTENDED_LAYOUT_MARKER;
    const std::size_t extension_offset = marker_present ? offset + sizeof(layout_marker) : offset;
    const std::size_t legacy_header = sizeof(mass_gauss_order) + sizeof(fixed_count) + ID_BOUNDARY;
    if (extension_offset <= payload.size() && legacy_header <= payload.size() - extension_offset) {
      std::memcpy(&mass_gauss_order, payload.data() + extension_offset, sizeof(mass_gauss_order));
      std::memcpy(&fixed_count, payload.data() + extension_offset + sizeof(mass_gauss_order), sizeof(fixed_count));
      std::memcpy(boundary_id.data(), payload.data() + extension_offset + sizeof(mass_gauss_order) + sizeof(fixed_count), boundary_id.size());
      const bool fields_valid = (mass_gauss_order == 3 || mass_gauss_order == 5) &&
                                fixed_count > 0 && fixed_count <= n &&
                                valid_c_string(boundary_id.data(), boundary_id.size());
      if (marker_present && !fields_valid) return 4;
      explicit_contract = marker_present || fields_valid;
      if (marker_present) offset += sizeof(layout_marker);
    }
  }
  if (explicit_contract) {
    offset += sizeof(mass_gauss_order) + sizeof(fixed_count) + boundary_id.size();
    model.mass_gauss_order = static_cast<std::size_t>(mass_gauss_order);
    model.boundary_contract_id = string_value(boundary_id.data(), boundary_id.size());
    model.fixed_dof.resize(static_cast<std::size_t>(fixed_count));
    model.prescribed_values.resize(static_cast<std::size_t>(fixed_count));
    for (std::size_t index = 0; index < model.fixed_dof.size(); ++index) {
      std::int32_t value = -1;
      if (!take(payload, offset, value) || value < 0) return 4;
      model.fixed_dof[index] = static_cast<std::size_t>(value);
    }
    for (double& value : model.prescribed_values) if (!take(payload, offset, value)) return 4;
  } else {
    // Canonical v1 requests retain the historical model byte layout.  Fill
    // the explicit contract from the protected defaults after dimensions are
    // assigned below.
    model.mass_gauss_order = 5;
    model.boundary_contract_id = "ancf_v1_bottom_top_xy_zero";
  }
  model.slice_positions_m.resize(static_cast<std::size_t>(slices));
  for (double& position : model.slice_positions_m) if (!take(payload, offset, position)) return 4;
  const std::size_t model_end = offset;
  model.elements = static_cast<std::size_t>(elements);
  model.slices = static_cast<std::size_t>(slices);
  if (!explicit_contract) {
    model.fixed_dof = {0u, 1u, 2u, 6u * model.elements, 6u * model.elements + 1u};
    model.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0};
  }
  model.dt_s = dt_s;
  try {
    cfd_ancf::validate_model(model);
  } catch (const std::exception&) {
    return 4;
  }
  std::int32_t base_n = 0, force_n = 0, mass_n = 0;
  if (!take(payload, offset, base_n) || !take(payload, offset, force_n) ||
      base_n != n || force_n != 3 * slices) return 5;
  // Select the layout from the complete frame length.  Guessing from the
  // first four bytes of run_id is ambiguous because those bytes are arbitrary
  // valid identity data and can equal n by coincidence.
  const std::size_t after_sizes = offset;
  const std::size_t fixed_suffix = ID_RUN + ID_CASE + 2 * ID_ENDPOINT + 32;
  const std::size_t legacy_arrays = static_cast<std::size_t>(4 * n) + static_cast<std::size_t>(force_n);
  const std::size_t extended_arrays = legacy_arrays + static_cast<std::size_t>(n) * static_cast<std::size_t>(n);
  const std::size_t legacy_size = fixed_suffix + legacy_arrays * sizeof(double);
  const std::size_t extended_size = sizeof(std::int32_t) + fixed_suffix + extended_arrays * sizeof(double);
  if (payload.size() - after_sizes == legacy_size) {
    mass_n = 0;
  } else if (payload.size() - after_sizes == extended_size) {
    if (!take(payload, offset, mass_n) || mass_n != n) return 5;
  } else {
    return 8;
  }

  char run_id[ID_RUN]{}, case_id[ID_CASE]{}, producer[ID_ENDPOINT]{}, consumer[ID_ENDPOINT]{};
  constexpr std::size_t identity_suffix = ID_RUN + ID_CASE + ID_ENDPOINT + ID_ENDPOINT + 32;
  if (offset > payload.size() || identity_suffix > payload.size() - offset) return 6;
  std::memcpy(run_id, payload.data() + offset, ID_RUN); offset += ID_RUN;
  std::memcpy(case_id, payload.data() + offset, ID_CASE); offset += ID_CASE;
  std::memcpy(producer, payload.data() + offset, ID_ENDPOINT); offset += ID_ENDPOINT;
  std::memcpy(consumer, payload.data() + offset, ID_ENDPOINT); offset += ID_ENDPOINT;
  std::array<unsigned char, 32> request_digest{};
  std::memcpy(request_digest.data(), payload.data() + offset, request_digest.size()); offset += request_digest.size();
  if (!valid_c_string(run_id, ID_RUN) || !valid_c_string(case_id, ID_CASE) ||
      !valid_c_string(producer, ID_ENDPOINT) || !valid_c_string(consumer, ID_ENDPOINT)) return 7;
  if (string_value(producer, ID_ENDPOINT) != REQUEST_PRODUCER ||
      string_value(consumer, ID_ENDPOINT) != REQUEST_CONSUMER) return 14;
  if (sequence != expected_sequence) return 13;
  // Structural dimensions live in the wire prefix rather than the physical
  // model-byte digest. Pin them for this worker segment so a later frame
  // cannot silently change ndof/elements/slices under the same model digest.
  if (expected_sequence == 1) {
    expected_n = n;
    expected_elements = elements;
    expected_slices = slices;
  } else if (n != expected_n || elements != expected_elements || slices != expected_slices) {
    return 16;
  }
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

  if (expected_sequence == 1) {
    expected_global_step = global_step;
    expected_bridge_step = bridge_step;
    expected_tick = integer_tick;
    expected_time_s = time_s;
    expected_dt_s = dt_s;
  } else if (lineage_mode == 0 && expected_sequence == 2) {
    if (global_step == expected_global_step && bridge_step == expected_bridge_step &&
        integer_tick == expected_tick && std::abs(time_s - expected_time_s) <= 1.0e-12 &&
        std::abs(dt_s - expected_dt_s) <= 1.0e-15) {
      lineage_mode = 2;
    } else {
      std::uint64_t expected_next_tick = 0;
      if (global_step == expected_global_step + 1 && bridge_step == expected_bridge_step + 1 &&
          next_tick(expected_tick, expected_dt_s, expected_next_tick) &&
          integer_tick == expected_next_tick &&
           canonical_time_tick(time_s, request_tick) && integer_tick == request_tick &&
          std::abs(time_s - (expected_time_s + expected_dt_s)) <= 1.0e-12 &&
          std::abs(dt_s - expected_dt_s) <= 1.0e-15) {
        lineage_mode = 1;
      } else {
        return 16;
      }
    }
  } else if (lineage_mode == 2 && expected_sequence % 2 == 0) {
    if (global_step != expected_global_step || bridge_step != expected_bridge_step ||
        integer_tick != expected_tick || std::abs(time_s - expected_time_s) > 1.0e-12 ||
        std::abs(dt_s - expected_dt_s) > 1.0e-15) return 16;
  } else {
    std::uint64_t expected_next_tick = 0;
    if (global_step != expected_global_step + 1 || bridge_step != expected_bridge_step + 1 ||
        !next_tick(expected_tick, expected_dt_s, expected_next_tick) ||
        integer_tick != expected_next_tick ||
         !canonical_time_tick(time_s, request_tick) || integer_tick != request_tick ||
        std::abs(time_s - (expected_time_s + expected_dt_s)) > 1.0e-12 ||
        std::abs(dt_s - expected_dt_s) > 1.0e-15) {
      std::cerr << "worker identity continuity mismatch at sequence " << sequence << '\n';
      return 16;
    }
  }
  // Advance the accepted lineage after every validated request.  Keeping the
  // first-step seed forever would reject the third and later contiguous steps.
  expected_global_step = global_step;
  expected_bridge_step = bridge_step;
  expected_tick = integer_tick;
  expected_time_s = time_s;
  expected_dt_s = dt_s;

  const std::size_t mass_count = mass_n == 0 ? 0u : static_cast<std::size_t>(mass_n) * static_cast<std::size_t>(mass_n);
  const std::size_t array_count = static_cast<std::size_t>(4 * n) + mass_count + static_cast<std::size_t>(force_n);
  if (array_count > (std::numeric_limits<std::size_t>::max)() / sizeof(double) ||
      offset > payload.size() || array_count * sizeof(double) != payload.size() - offset) return 8;
  std::vector<double> input(array_count);
  std::memcpy(input.data(), payload.data() + offset, input.size() * sizeof(double));
  std::vector<unsigned char> request_hash_bytes;
  request_hash_bytes.insert(request_hash_bytes.end(), payload.begin() + static_cast<std::ptrdiff_t>(model_start),
                            payload.begin() + static_cast<std::ptrdiff_t>(model_end));
  request_hash_bytes.insert(request_hash_bytes.end(), reinterpret_cast<unsigned char*>(input.data()),
                            reinterpret_cast<unsigned char*>(input.data()) + input.size() * sizeof(double));
  std::array<unsigned char, 32> calculated_request_digest{};
  if (!cfd_ancf::wire::sha256_bytes(request_hash_bytes, calculated_request_digest) || calculated_request_digest != request_digest ||
      !finite_values(input)) return 9;
  std::vector<unsigned char> model_bytes(
      payload.begin() + static_cast<std::ptrdiff_t>(model_start),
      payload.begin() + static_cast<std::ptrdiff_t>(model_end));
  std::array<unsigned char, 32> model_digest{};
  if (!cfd_ancf::wire::sha256_bytes(model_bytes, model_digest)) return 15;
  if (mass_n == 0 && external_contract_digest != nullptr) return 15;
  const std::size_t mass_count_for_hash = mass_n == 0 ? 0u : static_cast<std::size_t>(mass_n) * static_cast<std::size_t>(mass_n);
  const std::size_t mass_offset = 4u * static_cast<std::size_t>(n);
  if (mass_offset > input.size() || mass_count_for_hash > input.size() - mass_offset) return 15;
  std::vector<unsigned char> contract_bytes = model_bytes;
  if (mass_count_for_hash != 0u) {
    const auto* mass_begin = reinterpret_cast<const unsigned char*>(input.data() + mass_offset);
    contract_bytes.insert(contract_bytes.end(), mass_begin,
                          mass_begin + mass_count_for_hash * sizeof(double));
  }
  std::array<unsigned char, 32> contract_digest{};
  if (!cfd_ancf::wire::sha256_bytes(contract_bytes, contract_digest)) return 15;
  if (expected_sequence == 1) expected_full_contract_digest = contract_digest;
  else if (contract_digest != expected_full_contract_digest) return 16;
  if (external_contract_digest != nullptr && contract_digest != *external_contract_digest) return 15;
  if (expected_sequence == 1) expected_model_digest = model_digest;
  else if (model_digest != expected_model_digest) {
    std::cerr << "worker model digest mismatch at sequence " << sequence << '\n';
    return 16;
  }

  const std::vector<double> q(input.begin(), input.begin() + n);
  const std::vector<double> qdot(input.begin() + n, input.begin() + 2 * n);
  const std::vector<double> qddot(input.begin() + 2 * n, input.begin() + 3 * n);
  const std::vector<double> base_load(input.begin() + 3 * n, input.begin() + 4 * n);
  std::size_t input_offset = 4 * n;
  const std::vector<double> predictor = [&]() {
    std::vector<double> value(q.size());
    for (std::size_t index = 0; index < q.size(); ++index) {
      value[index] = q[index] + dt_s * qdot[index] + dt_s * dt_s * (0.5 - model.beta) * qddot[index];
    }
    return value;
  }();

  cfd_ancf::State state = cfd_ancf::make_reference_state(model);
  cfd_ancf::symmetrize_mass(state);
  if (mass_n != 0) {
    state.mass = cfd_ancf::Matrix(static_cast<std::size_t>(n), static_cast<std::size_t>(n));
    for (std::size_t row = 0; row < static_cast<std::size_t>(n); ++row) {
      for (std::size_t col = 0; col < static_cast<std::size_t>(n); ++col) {
        state.mass(row, col) = input[input_offset++];
      }
    }
    // The source MATLAB mass matrix is symmetrized before export. Reject a
    // mutated asymmetric matrix instead of changing the numerical contract
    // or feeding a non-symmetric inertia matrix into Newton.
    if (!exactly_symmetric(state.mass)) return 17;
  }
  const std::vector<double> slice_force(input.begin() + static_cast<std::ptrdiff_t>(input_offset), input.end());
  state.q = q; state.qdot = qdot; state.qddot = qddot; state.base_load = base_load;
  if (global_step <= 0 || time_s < dt_s) return 10;
  state.time_s = time_s - dt_s; state.step = static_cast<std::size_t>(global_step - 1);
  std::vector<double> internal_before; cfd_ancf::Matrix tangent;
  cfd_ancf::internal_force_tangent(state.q, model, internal_before, tangent);
  const std::vector<double> external = cfd_ancf::external_force(model, slice_force);
  std::vector<double> generalized = base_load;
  for (std::size_t index = 0; index < generalized.size(); ++index) generalized[index] += external[index];
  cfd_ancf::StepDiagnostics diagnostics;
  try {
    diagnostics = cfd_ancf::advance(state, model, slice_force);
  } catch (const std::exception&) {
    return 12;
  }
  // Do not report the request identity as a checkpoint unless the numerical
  // state reached the same step and time.  This closes a masking path where a
  // rounding or state-update defect could be hidden by echoing request fields.
  if (state.step != static_cast<std::size_t>(global_step) ||
      !std::isfinite(state.time_s) ||
      std::abs(state.time_s - time_s) > 1.0e-12) {
    return 16;
  }
  if (!append_profile(global_step, sequence, diagnostics)) return 19;
  std::vector<double> internal_after; cfd_ancf::internal_force_tangent(state.q, model, internal_after, tangent);
  const std::vector<double> corrector = state.q;
  const std::vector<double> output_arrays = [&]() {
    std::vector<double> value; value.reserve(8 * q.size());
    // v1 is a positional wire schema. The historical MATLAB golden record
    // calls both force slots external_force and generalized_force, but both
    // contain total Qext = base_load + mapped slice force. Do not reinterpret
    // either slot as CFD-only force without a versioned schema migration.
    const std::array<const std::vector<double>*, 8> vectors{
        &state.q, &state.qdot, &state.qddot, &internal_after,
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
  if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
      _setmode(_fileno(stdout), _O_BINARY) == -1) {
    std::cerr << "failed to set stdin/stdout binary mode\n";
    return BINARY_MODE_FAILURE;
  }
#endif
  std::uint32_t last_sequence = 0;
  std::string expected_run;
  std::string expected_case;
  std::int32_t expected_global_step = 0, expected_bridge_step = 0;
  std::uint64_t expected_tick = 0;
  double expected_time_s = 0.0, expected_dt_s = 0.0;
  std::int32_t expected_n = 0, expected_elements = 0, expected_slices = 0;
  int lineage_mode = 0;
  std::array<unsigned char, 32> expected_model_digest{};
  std::array<unsigned char, 32> expected_full_contract_digest{};
  std::array<unsigned char, 32> expected_contract_digest{};
  std::string expected_contract_text;
  bool has_expected_contract = false;
#ifdef _WIN32
  char* raw_expected_contract = nullptr;
  std::size_t raw_expected_contract_size = 0;
  if (_dupenv_s(&raw_expected_contract, &raw_expected_contract_size,
                "CFD_ANCF_EXPECTED_MODEL_CONTRACT_SHA256") != 0) return 25;
  if (raw_expected_contract != nullptr) {
    has_expected_contract = true;
    expected_contract_text.assign(raw_expected_contract);
    std::free(raw_expected_contract);
  }
#else
  const char* raw_expected_contract = std::getenv("CFD_ANCF_EXPECTED_MODEL_CONTRACT_SHA256");
  if (raw_expected_contract != nullptr) {
    has_expected_contract = true;
    expected_contract_text.assign(raw_expected_contract);
  }
#endif
  if (has_expected_contract && !decode_sha256_hex(expected_contract_text.c_str(), expected_contract_digest)) return 25;
  std::unordered_set<std::uint64_t> seen_request_ids, seen_transaction_ids;
  bool initialized = false;
  const bool allow_offline_direct = environment_is_one("CFD_ANCF_OFFLINE_DIRECT_WORKER");
  while (true) {
    std::array<char, 8> magic{}; std::uint32_t length = 0, message_type = 0;
    // A clean worker exit requires the explicit SHUTDOWN control frame.  EOF
    // before that frame is an owner disconnect and must fail closed.
    if (!read_bytes(std::cin, magic.data(), magic.size())) return UNEXPECTED_EOF;
    if (!read_bytes(std::cin, reinterpret_cast<char*>(&length), sizeof(length)) ||
        !read_bytes(std::cin, reinterpret_cast<char*>(&message_type), sizeof(message_type)) || magic != MAGIC) return 2;
    if (length > 64u * 1024u * 1024u) return 3;
    if (message_type == 3) { if (length != 0) return 4; return 0; }
    if (message_type == 4) {
      if (length != 0 || initialized) return 4;
      initialized = true;
      // Explicitly identify the full ANCF worker before any step is accepted.
      // This prevents the legacy transport-only executable from being used by
      // the production coordinator while retaining the direct-worker legacy
      // entry point for low-level protocol tests.
      std::array<char, 32> role{};
      std::memcpy(role.data(), WORKER_ROLE,
                  (std::min)(std::strlen(WORKER_ROLE), role.size() - 1));
      std::vector<char> hello;
      append(hello, SCHEMA); append(hello, PROTOCOL); append(hello, INITIALIZE_ACK);
      hello.insert(hello.end(), role.begin(), role.end());
      const auto hello_length = static_cast<std::uint32_t>(hello.size());
      std::cout.write(MAGIC.data(), MAGIC.size());
      std::cout.write(reinterpret_cast<const char*>(&hello_length), sizeof(hello_length));
      std::cout.write(reinterpret_cast<const char*>(&INITIALIZE_ACK), sizeof(INITIALIZE_ACK));
      std::cout.write(hello.data(), static_cast<std::streamsize>(hello.size()));
      std::cout.flush();
      if (!std::cout) return OUTPUT_WRITE_FAILURE;
      continue;
    }
    if (message_type != STEP_REQUEST) return 5;
    // Production sessions must complete the explicit role handshake. Direct
    // requests are retained only for offline protocol fixtures and require an
    // explicit environment opt-in that production coordinators never set.
    if (!initialized && !allow_offline_direct) return 4;
    initialized = true;
    std::vector<char> payload(length);
    if (!read_bytes(std::cin, payload.data(), payload.size())) return 6;
    std::vector<char> response;
    int result = 0;
    try {
      result = process_step(payload, response, last_sequence + 1, expected_run, expected_case,
                            expected_global_step, expected_bridge_step, expected_tick,
                            expected_time_s, expected_dt_s, expected_n, expected_elements,
                            expected_slices, expected_model_digest, lineage_mode,
                            expected_full_contract_digest,
                            has_expected_contract ? &expected_contract_digest : nullptr,
                            seen_request_ids, seen_transaction_ids);
    } catch (const std::exception& error) {
      std::cerr << "worker exception: " << error.what() << '\n';
      return 20;
    }
    if (result != 0) return result;
    std::uint32_t response_length = static_cast<std::uint32_t>(response.size());
    std::cout.write(MAGIC.data(), MAGIC.size());
    std::cout.write(reinterpret_cast<const char*>(&response_length), sizeof(response_length));
    std::cout.write(reinterpret_cast<const char*>(&STEP_RESPONSE), sizeof(STEP_RESPONSE));
    std::cout.write(response.data(), static_cast<std::streamsize>(response.size()));
    std::cout.flush();
    if (!std::cout) return OUTPUT_WRITE_FAILURE;
    ++last_sequence;
  }
}
