#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <unordered_set>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#include <fcntl.h>
#include <io.h>
#endif

namespace {
constexpr std::array<char, 8> MAGIC{'C','F','D','A','N','C','F','1'};
constexpr std::uint32_t SCHEMA = 1;
constexpr std::uint32_t PROTOCOL = 1;
constexpr std::size_t ID_RUN=64, ID_CASE=64, ID_ENDPOINT=32;
template <class T> bool read(std::istream& in, T& value) { return static_cast<bool>(in.read(reinterpret_cast<char*>(&value), sizeof(T))); }
template <class T> void append(std::vector<char>& out, const T& value) { const auto* p = reinterpret_cast<const char*>(&value); out.insert(out.end(), p, p + sizeof(T)); }
bool read_bytes(std::istream& in, char* p, std::size_t n) { return static_cast<bool>(in.read(p, static_cast<std::streamsize>(n))); }
bool c_string_valid(const char* p, std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) {
    if (p[i] == '\0') return true;
    if (static_cast<unsigned char>(p[i]) < 0x20) return false;
  }
  return false;
}
bool finite_values(const std::vector<double>& values) {
  for (double value : values) if (!std::isfinite(value)) return false;
  return true;
}
bool little_endian() {
  const std::uint16_t marker = 1;
  return *reinterpret_cast<const std::uint8_t*>(&marker) == 1;
}
bool sha256(const std::vector<double>& values, std::array<unsigned char, 32>& digest) {
#ifdef _WIN32
  BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
  DWORD object_length = 0, bytes = 0;
  if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0) return false;
  bool ok = BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&object_length), sizeof(object_length), &bytes, 0) == 0;
  std::vector<unsigned char> object(object_length);
  if (ok) ok = BCryptCreateHash(algorithm, &hash, object.data(), object_length, nullptr, 0, 0) == 0;
  if (ok) ok = BCryptHashData(hash, reinterpret_cast<PUCHAR>(const_cast<double*>(values.data())), static_cast<ULONG>(values.size() * sizeof(double)), 0) == 0;
  if (ok) ok = BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) == 0;
  if (hash != nullptr) BCryptDestroyHash(hash); if (algorithm != nullptr) BCryptCloseAlgorithmProvider(algorithm, 0);
  return ok;
#else
  (void)values; (void)digest; return false;
#endif
}
}

int main() {
  if (!little_endian()) return 21;
#ifdef _WIN32
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  std::uint32_t last_sequence = 0; std::string expected_run, expected_case;
  std::int32_t expected_step = 0, expected_bridge = 0;
  std::uint64_t expected_tick = 0;
  double expected_time_s = 0.0, expected_dt_s = 0.0;
  std::unordered_set<std::uint64_t> seen_request_ids, seen_transaction_ids;
  while (true) {
    std::array<char, 8> magic{}; std::uint32_t length=0, count=0;
    if (!read_bytes(std::cin, magic.data(), magic.size())) return 0;
    if (!read(std::cin, length) || !read(std::cin, count) || magic != MAGIC || length > 64u*1024u*1024u) return 2;
    if (count == 3) { if (length != 0) return 2; return 0; }
    if (count == 4) { if (length != 0) return 2; continue; }
    if (count != 1) return 2;
    std::vector<char> payload(length);
    if (!read_bytes(std::cin, payload.data(), payload.size())) return 3;
    if (payload.size() < 288) return 4;
    std::uint32_t schema=0, protocol=0, sequence=0; std::int32_t step=0, bridge=0; std::uint64_t tick=0, request_id=0, transaction_id=0; double time_s=0.0, dt_s=0.0; std::int32_t n=0;
    std::size_t offset=0;
    auto take = [&](auto& v) { if (offset + sizeof(v) > payload.size()) return false; std::memcpy(&v, payload.data()+offset, sizeof(v)); offset += sizeof(v); return true; };
    char run_id[ID_RUN]{}, case_id[ID_CASE]{}, producer[ID_ENDPOINT]{}, consumer[ID_ENDPOINT]{};
    if (!take(schema)||!take(protocol)||!take(sequence)||!take(step)||!take(bridge)||!take(tick)||!take(time_s)||!take(dt_s)||!take(n)||!take(request_id)||!take(transaction_id) || schema != SCHEMA || protocol != PROTOCOL || n <= 0 || n > 100000 || step <= 0 || request_id == 0 || transaction_id == 0) return 5;
    // The fixed identity fields follow the numeric header.
    if (offset + ID_RUN + ID_CASE + ID_ENDPOINT + ID_ENDPOINT > payload.size()) return 5;
    std::memcpy(run_id, payload.data()+offset, ID_RUN); offset += ID_RUN;
    std::memcpy(case_id, payload.data()+offset, ID_CASE); offset += ID_CASE;
    std::memcpy(producer, payload.data()+offset, ID_ENDPOINT); offset += ID_ENDPOINT;
    std::memcpy(consumer, payload.data()+offset, ID_ENDPOINT); offset += ID_ENDPOINT;
    std::array<unsigned char, 32> request_digest{};
    if (offset + request_digest.size() > payload.size()) return 5;
    std::memcpy(request_digest.data(), payload.data()+offset, request_digest.size()); offset += request_digest.size();
    const std::size_t expected = 288u + static_cast<std::size_t>(n) * 3u * sizeof(double);
    if (!std::isfinite(time_s) || !std::isfinite(dt_s)) return 6;
    if (time_s < 0.0 || time_s > 1.0e9) return 6;
    const auto expected_tick_from_time = static_cast<std::uint64_t>(std::llround(time_s * 1.0e9));
    if (payload.size() != expected || dt_s <= 0.0 || bridge <= 0 || sequence == 0 || sequence != last_sequence + 1 ||
        tick != expected_tick_from_time || time_s < dt_s || (sequence == 1 && bridge != 1) ||
        seen_request_ids.count(request_id) != 0 || seen_transaction_ids.count(transaction_id) != 0 ||
        !std::isfinite(time_s) || !std::isfinite(dt_s) || !c_string_valid(run_id, ID_RUN) || !c_string_valid(case_id, ID_CASE) ||
        !c_string_valid(producer, ID_ENDPOINT) || !c_string_valid(consumer, ID_ENDPOINT)) return 6;
    const std::string run_value(run_id, strnlen_s(run_id, ID_RUN));
    const std::string case_value(case_id, strnlen_s(case_id, ID_CASE));
    if (expected_run.empty()) { expected_run = run_value; expected_case = case_value; }
    if (run_value != expected_run || case_value != expected_case) return 7;
    if (sequence > 1 && (step != expected_step + 1 || bridge != expected_bridge + 1 ||
                         tick != expected_tick + static_cast<std::uint64_t>(std::llround(expected_dt_s * 1.0e9)) ||
                         std::abs(time_s - (expected_time_s + expected_dt_s)) > 1.0e-12 ||
                         std::abs(dt_s - expected_dt_s) > 1.0e-15)) return 7;
    seen_request_ids.insert(request_id);
    seen_transaction_ids.insert(transaction_id);
    expected_step = step; expected_bridge = bridge; expected_tick = tick;
    expected_time_s = time_s; expected_dt_s = dt_s;
    std::vector<double> values(static_cast<std::size_t>(n)*3u);
    std::memcpy(values.data(), payload.data()+offset, values.size()*sizeof(double));
    if (!finite_values(values)) return 8;
    std::array<unsigned char, 32> calculated_request_digest{};
    if (!sha256(values, calculated_request_digest) || calculated_request_digest != request_digest) return 8;
    std::vector<char> response;
    append(response, schema); append(response, protocol); append(response, sequence); append(response, step); append(response, bridge); append(response, tick); append(response, time_s);
    append(response, n); std::int32_t return_code=0; append(response, return_code);
    std::vector<double> response_values; response_values.reserve(values.size());
    for (int i=0;i<n;++i) response_values.push_back(values[static_cast<std::size_t>(i)] + dt_s*values[static_cast<std::size_t>(n+i)]);
    for (int i=0;i<n;++i) response_values.push_back(values[static_cast<std::size_t>(n+i)]);
    for (int i=0;i<n;++i) response_values.push_back(values[static_cast<std::size_t>(2*n+i)]);
    std::array<unsigned char,32> digest{}; if (!sha256(response_values, digest)) return 9;
    response.insert(response.end(), reinterpret_cast<char*>(digest.data()), reinterpret_cast<char*>(digest.data()+digest.size())); append(response, transaction_id); append(response, request_id); const std::uint32_t ack = 1; append(response, ack);
    response.insert(response.end(), run_id, run_id + ID_RUN); response.insert(response.end(), case_id, case_id + ID_CASE);
    response.insert(response.end(), consumer, consumer + ID_ENDPOINT); response.insert(response.end(), producer, producer + ID_ENDPOINT);
    // Reference transport worker: preserves state dimensions and transaction
    // identity. Production ANCF kernels are plugged in only after dual-run.
    for (double value : response_values) append(response, value);
    const std::uint32_t response_length = static_cast<std::uint32_t>(response.size());
    const std::uint32_t response_type = 2;
    std::cout.write(MAGIC.data(), MAGIC.size()); std::cout.write(reinterpret_cast<const char*>(&response_length), sizeof(response_length)); std::cout.write(reinterpret_cast<const char*>(&response_type), sizeof(response_type)); std::cout.write(response.data(), static_cast<std::streamsize>(response.size())); std::cout.flush();
    last_sequence = sequence;
  }
}
