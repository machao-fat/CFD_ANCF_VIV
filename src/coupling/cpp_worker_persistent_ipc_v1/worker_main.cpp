#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdlib>
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
constexpr int UNEXPECTED_EOF = 22;
constexpr int OUTPUT_WRITE_FAILURE = 23;
constexpr int BINARY_MODE_FAILURE = 24;
constexpr std::uint32_t SCHEMA = 1;
constexpr std::uint32_t PROTOCOL = 1;
constexpr std::size_t ID_RUN=64, ID_CASE=64, ID_ENDPOINT=32;
constexpr std::size_t MAX_NDOF = 2048;
constexpr char REQUEST_PRODUCER[] = "python_scheduler";
constexpr char REQUEST_CONSUMER[] = "cpp_ancf_worker";
template <class T> bool read(std::istream& in, T& value) { return static_cast<bool>(in.read(reinterpret_cast<char*>(&value), sizeof(T))); }
template <class T> void append(std::vector<char>& out, const T& value) { const auto* p = reinterpret_cast<const char*>(&value); out.insert(out.end(), p, p + sizeof(T)); }
bool read_bytes(std::istream& in, char* p, std::size_t n) { return static_cast<bool>(in.read(p, static_cast<std::streamsize>(n))); }
bool c_string_valid(const char* p, std::size_t n) {
  bool terminated = false;
  for (std::size_t i = 0; i < n; ++i) {
    if (p[i] == '\0') {
      if (i == 0) return false;
      terminated = true;
      for (++i; i < n; ++i) if (p[i] != '\0') return false;
      break;
    }
    if (static_cast<unsigned char>(p[i]) < 0x20) return false;
  }
  return terminated;
}
std::size_t bounded_length(const char* p, std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) if (p[i] == '\0') return i;
  return n;
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
bool finite_values(const std::vector<double>& values) {
  for (double value : values) if (!std::isfinite(value)) return false;
  return true;
}
bool little_endian() {
  const std::uint16_t marker = 1;
  return *reinterpret_cast<const std::uint8_t*>(&marker) == 1;
}
std::uint32_t rotr(std::uint32_t value, unsigned count) {
  return (value >> count) | (value << (32u - count));
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
  // Keep the wire hash independent of platform crypto libraries.  The
  // worker already rejects non-little-endian hosts, so the byte view is the
  // canonical little-endian IEEE-754 representation used by Python.
  static constexpr std::uint32_t k[64] = {
      0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
      0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
      0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
      0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
      0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
      0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
      0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
      0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u};
  std::vector<unsigned char> bytes(values.size() * sizeof(double));
  if (!bytes.empty()) std::memcpy(bytes.data(), values.data(), bytes.size());
  const std::uint64_t bit_length = static_cast<std::uint64_t>(bytes.size()) * 8u;
  bytes.push_back(0x80u);
  while ((bytes.size() % 64u) != 56u) bytes.push_back(0u);
  for (int shift = 56; shift >= 0; shift -= 8) bytes.push_back(static_cast<unsigned char>(bit_length >> shift));
  std::uint32_t h[8] = {0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
                        0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};
  for (std::size_t block = 0; block < bytes.size(); block += 64u) {
    std::uint32_t w[64]{};
    for (int i = 0; i < 16; ++i) {
      const std::size_t p = block + static_cast<std::size_t>(4 * i);
      w[i] = (static_cast<std::uint32_t>(bytes[p]) << 24u) |
             (static_cast<std::uint32_t>(bytes[p + 1]) << 16u) |
             (static_cast<std::uint32_t>(bytes[p + 2]) << 8u) |
             static_cast<std::uint32_t>(bytes[p + 3]);
    }
    for (int i = 16; i < 64; ++i) {
      const std::uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
      const std::uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    std::uint32_t a=h[0], b=h[1], c=h[2], d=h[3], e=h[4], f=h[5], g=h[6], hh=h[7];
    for (int i = 0; i < 64; ++i) {
      const std::uint32_t s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const std::uint32_t ch = (e & f) ^ ((~e) & g);
      const std::uint32_t temp1 = hh + s1 + ch + k[i] + w[i];
      const std::uint32_t s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t temp2 = s0 + maj;
      hh=g; g=f; f=e; e=d+temp1; d=c; c=b; b=a; a=temp1+temp2;
    }
    h[0]+=a; h[1]+=b; h[2]+=c; h[3]+=d; h[4]+=e; h[5]+=f; h[6]+=g; h[7]+=hh;
  }
  for (int i = 0; i < 8; ++i) {
    digest[4*i] = static_cast<unsigned char>(h[i] >> 24u);
    digest[4*i+1] = static_cast<unsigned char>(h[i] >> 16u);
    digest[4*i+2] = static_cast<unsigned char>(h[i] >> 8u);
    digest[4*i+3] = static_cast<unsigned char>(h[i]);
  }
  return true;
#endif
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
  std::uint32_t last_sequence = 0; std::string expected_run, expected_case;
  std::int32_t expected_step = 0, expected_bridge = 0;
  std::uint64_t expected_tick = 0;
  double expected_time_s = 0.0, expected_dt_s = 0.0;
  std::unordered_set<std::uint64_t> seen_request_ids, seen_transaction_ids;
  bool initialized = false;
  const bool allow_legacy_direct = environment_is_one("CFD_ANCF_OFFLINE_LEGACY_TRANSPORT");
  while (true) {
    std::array<char, 8> magic{}; std::uint32_t length=0, count=0;
    // A clean worker exit requires the explicit SHUTDOWN control frame.  EOF
    // before that frame is an owner disconnect and must fail closed.
    if (!read_bytes(std::cin, magic.data(), magic.size())) return UNEXPECTED_EOF;
    if (!read(std::cin, length) || !read(std::cin, count) || magic != MAGIC || length > 64u*1024u*1024u) return 2;
    if (count == 3) { if (length != 0) return 2; return 0; }
    if (count == 4) {
      if (length != 0 || initialized) return 2;
      initialized = true;
      continue;
    }
    if (count != 1) return 2;
    // This executable is transport-only legacy code.  It is never a
    // production worker and accepts direct step frames only for an explicit
    // offline fixture invocation.
    if (!initialized && !allow_legacy_direct) return 4;
    initialized = true;
    std::vector<char> payload(length);
    if (!read_bytes(std::cin, payload.data(), payload.size())) return 3;
    if (payload.size() < 288) return 4;
    std::uint32_t schema=0, protocol=0, sequence=0; std::int32_t step=0, bridge=0; std::uint64_t tick=0, request_id=0, transaction_id=0; double time_s=0.0, dt_s=0.0; std::int32_t n=0;
    std::size_t offset=0;
    auto take = [&](auto& v) { if (offset > payload.size() || sizeof(v) > payload.size() - offset) return false; std::memcpy(&v, payload.data()+offset, sizeof(v)); offset += sizeof(v); return true; };
    char run_id[ID_RUN]{}, case_id[ID_CASE]{}, producer[ID_ENDPOINT]{}, consumer[ID_ENDPOINT]{};
    if (!take(schema)||!take(protocol)||!take(sequence)||!take(step)||!take(bridge)||!take(tick)||!take(time_s)||!take(dt_s)||!take(n)||!take(request_id)||!take(transaction_id) || schema != SCHEMA || protocol != PROTOCOL || n <= 0 || static_cast<std::size_t>(n) > MAX_NDOF || step <= 0 || request_id == 0 || transaction_id == 0) return 5;
    // The fixed identity fields follow the numeric header.
    constexpr std::size_t identity_bytes = ID_RUN + ID_CASE + ID_ENDPOINT + ID_ENDPOINT;
    if (offset > payload.size() || identity_bytes > payload.size() - offset) return 5;
    std::memcpy(run_id, payload.data()+offset, ID_RUN); offset += ID_RUN;
    std::memcpy(case_id, payload.data()+offset, ID_CASE); offset += ID_CASE;
    std::memcpy(producer, payload.data()+offset, ID_ENDPOINT); offset += ID_ENDPOINT;
    std::memcpy(consumer, payload.data()+offset, ID_ENDPOINT); offset += ID_ENDPOINT;
    std::array<unsigned char, 32> request_digest{};
    if (offset > payload.size() || request_digest.size() > payload.size() - offset) return 5;
    std::memcpy(request_digest.data(), payload.data()+offset, request_digest.size()); offset += request_digest.size();
    const std::size_t expected = 288u + static_cast<std::size_t>(n) * 3u * sizeof(double);
    if (!std::isfinite(time_s) || !std::isfinite(dt_s)) return 6;
    if (time_s < 0.0 || time_s > 1.0e9) return 6;
    const auto expected_tick_from_time = static_cast<std::uint64_t>(std::llround(time_s * 1.0e9));
    if (payload.size() != expected || dt_s <= 0.0 || dt_s > 1.0e9 || bridge <= 0 || sequence == 0 ||
        (last_sequence == 0xFFFFFFFFu ? true : sequence != last_sequence + 1) ||
        tick != expected_tick_from_time || time_s < dt_s || (sequence == 1 && bridge != 1) ||
        seen_request_ids.count(request_id) != 0 || seen_transaction_ids.count(transaction_id) != 0 ||
        !std::isfinite(time_s) || !std::isfinite(dt_s) || !c_string_valid(run_id, ID_RUN) || !c_string_valid(case_id, ID_CASE) ||
        !c_string_valid(producer, ID_ENDPOINT) || !c_string_valid(consumer, ID_ENDPOINT) ||
         std::string(producer, bounded_length(producer, ID_ENDPOINT)) != REQUEST_PRODUCER ||
         std::string(consumer, bounded_length(consumer, ID_ENDPOINT)) != REQUEST_CONSUMER) return 6;
    const std::string run_value(run_id, bounded_length(run_id, ID_RUN));
    const std::string case_value(case_id, bounded_length(case_id, ID_CASE));
    if (expected_run.empty()) { expected_run = run_value; expected_case = case_value; }
    if (run_value != expected_run || case_value != expected_case) return 7;
    if (sequence > 1 && (step != expected_step + 1 || bridge != expected_bridge + 1 ||
                         tick != expected_tick + static_cast<std::uint64_t>(std::llround(expected_dt_s * 1.0e9)) ||
                         std::abs(time_s - (expected_time_s + expected_dt_s)) > 1.0e-12 ||
                         std::abs(dt_s - expected_dt_s) > 1.0e-15)) return 7;
    constexpr std::size_t max_seen_identities = 100000;
    if (seen_request_ids.size() >= max_seen_identities || seen_transaction_ids.size() >= max_seen_identities) return 10;
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
    if (!std::cout) return OUTPUT_WRITE_FAILURE;
    last_sequence = sequence;
  }
}
