// ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1
// Validation-only production harness.
// No production source is modified by this file.
#include "ancf_kernel.hpp"

#define NOMINMAX
#include <algorithm>
#include <array>
#include <windows.h>
#include <bcrypt.h>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#pragma comment(lib, "bcrypt.lib")

using cfd_ancf::Matrix;
using Vec3 = std::array<double, 3>;

namespace {

constexpr char kProtocolSha[] =
    "6A5E7AD8FC9B42A9BAE4B221A6BDDA595A6BFF463072331D5F199E866BF256C4";
constexpr char kCommit[] =
    "36927c01208339f179670322799eb84d86dd2992";
constexpr char kParent[] =
    "b5e22a2fdba5961dabc2ed62a9d833f6bf649c5a";
constexpr char kKernelSha[] =
    "2E69383D14960E0B16710736F00805D5E4EC18658725852E49156FABA3819D3B";
constexpr char kHeaderSha[] =
    "DA866C2CA1E25B620111551251C00E46F05F6BC8981FCFE6F0CC095D5794A6FB";
constexpr char kWorkerSha[] =
    "16D1BA919C31036712B322594041CFDF304D0EC3426B9FB04940D753FD4927AD";
const std::filesystem::path kKernelRelative =
    std::filesystem::path("src") / "coupling" /
    "cpp_worker_persistent_ipc_v1" / "ancf_kernel.cpp";
const std::filesystem::path kHeaderRelative =
    std::filesystem::path("src") / "coupling" /
    "cpp_worker_persistent_ipc_v1" / "ancf_kernel.hpp";
const std::filesystem::path kWorkerRelative =
    std::filesystem::path("src") / "coupling" /
    "cpp_worker_persistent_ipc_v1" / "ancf_worker_main.cpp";
const std::filesystem::path kProtocolRelative =
    std::filesystem::path("src") / "coupling" /
    "cpp_worker_persistent_ipc_v1" / "kernel_protocol.py";
const std::filesystem::path kReferenceRelative =
    std::filesystem::path("runtime") / "ANCF_validation" /
    "ANCF_G1_EXTENSIBLE_CABLE_REFERENCE.csv";
constexpr char kBoundaryId[] =
    "ancf_g1_v1_2_fixed_endpoint_positions_potential_static";
constexpr double kL0 = 170.0;
constexpr double kXTarget = 100.0;
constexpr double kZTarget = 50.0;
constexpr double kDEff = 0.062173949528721434;
constexpr double kEEff = 1.646884758815142e11;
constexpr double kRhoMEff = 54347.197040899686;
constexpr double kRhoFEff = 40567.052980132445;
constexpr double kGravity = 9.807;
constexpr std::size_t kMaxNewton = 40;
constexpr double kNewtonTolerance = 1.0e-8;
constexpr std::size_t kGaussOrder = 3;
constexpr std::size_t kMassGaussOrder = 5;
constexpr std::size_t kCenterlineSamples = 1001;
constexpr double kC1 = 1.0e-4;
constexpr std::size_t kBetaCount = 13;

constexpr std::array<double, 6> kTargets{
    47.11e3, 26.60e3, 45.71e3, 11.40e3, 24.04e3, 11.40e3};

std::filesystem::path g_repo_root;
std::filesystem::path g_evidence_root;

std::string trim_line(std::string value) {
  while (!value.empty() && (value.back() == '\n' || value.back() == '\r'))
    value.pop_back();
  return value;
}

std::string sha256_file(const std::filesystem::path& path) {
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  ULONG object_length = 0;
  ULONG digest_length = 0;
  ULONG result_length = 0;
  if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM,
                                  nullptr, 0) != 0 ||
      BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                        reinterpret_cast<PUCHAR>(&object_length),
                        sizeof(object_length), &result_length, 0) != 0 ||
      BCryptGetProperty(algorithm, BCRYPT_HASH_LENGTH,
                        reinterpret_cast<PUCHAR>(&digest_length),
                        sizeof(digest_length), &result_length, 0) != 0) {
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    throw std::runtime_error("cannot initialize SHA-256 provider");
  }
  std::vector<unsigned char> object(object_length);
  std::vector<unsigned char> digest(digest_length);
  if (BCryptCreateHash(algorithm, &hash, object.data(), object_length,
                       nullptr, 0, 0) != 0) {
    BCryptCloseAlgorithmProvider(algorithm, 0);
    throw std::runtime_error("cannot create SHA-256 hash");
  }
  std::ifstream input;
  input.open(path, std::ios::binary);
  if (!input) {
    BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    throw std::runtime_error("cannot open identity file");
  }
  std::array<char, 1 << 16> buffer{};
  while (input) {
    input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize count = input.gcount();
    if (count > 0 &&
        BCryptHashData(hash, reinterpret_cast<PUCHAR>(buffer.data()),
                       static_cast<ULONG>(count), 0) != 0) {
      BCryptDestroyHash(hash);
      BCryptCloseAlgorithmProvider(algorithm, 0);
      throw std::runtime_error("SHA-256 update failed");
    }
  }
  if (BCryptFinishHash(hash, digest.data(), digest_length, 0) != 0) {
    BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    throw std::runtime_error("SHA-256 finalization failed");
  }
  BCryptDestroyHash(hash);
  BCryptCloseAlgorithmProvider(algorithm, 0);
  std::ostringstream output;
  output << std::uppercase << std::hex << std::setfill('0');
  for (unsigned char value : digest)
    output << std::setw(2) << static_cast<unsigned int>(value);
  return output.str();
}

struct CommandLineOptions {
  bool identity_only = false;
  std::filesystem::path repo_root;
  std::filesystem::path evidence_root;
};

std::string path_utf8(const std::filesystem::path& path) {
  return path.u8string();
}

std::filesystem::path canonical_path(const std::filesystem::path& path) {
  std::error_code error;
  const std::filesystem::path result =
      std::filesystem::weakly_canonical(path, error);
  if (error) throw std::runtime_error("cannot canonicalize path: " + path_utf8(path));
  return result;
}

CommandLineOptions parse_options(int argc, wchar_t** argv) {
  CommandLineOptions options;
  options.repo_root = std::filesystem::current_path();
  options.evidence_root = options.repo_root;
  for (int i = 1; i < argc; ++i) {
    const std::wstring argument(argv[i]);
    if (argument == L"--identity-only") {
      options.identity_only = true;
    } else if (argument == L"--repo-root" || argument == L"--evidence-root") {
      if (i + 1 >= argc) throw std::runtime_error("missing path option value");
      const std::filesystem::path value(argv[++i]);
      if (argument == L"--repo-root") options.repo_root = value;
      else options.evidence_root = value;
    } else {
      throw std::runtime_error("unknown command-line option");
    }
  }
  options.repo_root = canonical_path(options.repo_root);
  options.evidence_root = canonical_path(options.evidence_root);
  if (!std::filesystem::is_directory(options.repo_root))
    throw std::runtime_error("repository root is not a directory");
  if (!std::filesystem::is_directory(options.evidence_root))
    throw std::runtime_error("evidence root is not a directory");
  return options;
}

std::string git_revision(const wchar_t* selector) {
  const std::wstring command =
      L"git -C \"" + g_repo_root.wstring() + L"\" rev-parse " + selector;
  FILE* pipe = _wpopen(command.c_str(), L"r");
  if (!pipe) throw std::runtime_error("cannot query git revision");
  std::string output;
  std::array<char, 256> buffer{};
  while (std::fgets(buffer.data(), static_cast<int>(buffer.size()), pipe))
    output += buffer.data();
  const int status = _pclose(pipe);
  if (status != 0) throw std::runtime_error("git revision query failed");
  return trim_line(output);
}

std::string git_head() { return git_revision(L"HEAD"); }
std::string git_parent() { return git_revision(L"HEAD~1"); }

void identity_checkpoint(const char* label) {
  const std::string commit = git_head();
  const std::string parent = git_parent();
  const std::string kernel = sha256_file(g_repo_root / kKernelRelative);
  const std::string header = sha256_file(g_repo_root / kHeaderRelative);
  const std::string worker = sha256_file(g_repo_root / kWorkerRelative);
  const std::string protocol = sha256_file(g_repo_root / kProtocolRelative);
  if (commit != kCommit || parent != kParent || kernel != kKernelSha ||
      header != kHeaderSha || worker != kWorkerSha || protocol != kProtocolSha) {
    throw std::runtime_error(std::string("SOURCE_IDENTITY_CHANGED at ") +
                             label + " commit=" + commit + " parent=" +
                             parent + " kernel=" + kernel + " header=" +
                             header + " worker=" + worker + " protocol=" +
                             protocol);
  }
}

std::string json_escape(const std::string& value) {
  std::ostringstream output;
  for (const unsigned char character : value) {
    switch (character) {
      case '\\': output << "\\\\"; break;
      case '"': output << "\\\""; break;
      case '\n': output << "\\n"; break;
      case '\r': output << "\\r"; break;
      case '\t': output << "\\t"; break;
      default:
        if (character < 0x20) {
          output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                 << static_cast<unsigned int>(character) << std::dec;
        } else {
          output << character;
        }
    }
  }
  return output.str();
}

struct IdentityEntry {
  std::string logical_name;
  std::filesystem::path path;
  std::string expected_sha256;
};

void add_identity_entry(std::vector<IdentityEntry>& entries,
                        const std::string& logical_name,
                        const std::filesystem::path& path,
                        const std::string& expected_sha256) {
  entries.push_back({logical_name, path, expected_sha256});
}

std::vector<IdentityEntry> required_identity_entries() {
  const std::filesystem::path current_evidence =
      g_repo_root / "runtime" / "ANCF_validation";
  const std::filesystem::path historical_evidence =
      g_evidence_root / "runtime" / "ANCF_validation";
  std::vector<IdentityEntry> entries;
  add_identity_entry(entries, "production/ancf_kernel.cpp",
                     g_repo_root / kKernelRelative, kKernelSha);
  add_identity_entry(entries, "production/ancf_kernel.hpp",
                     g_repo_root / kHeaderRelative, kHeaderSha);
  add_identity_entry(entries, "production/ancf_worker_main.cpp",
                     g_repo_root / kWorkerRelative, kWorkerSha);
  add_identity_entry(entries, "production/kernel_protocol.py",
                     g_repo_root / kProtocolRelative, kProtocolSha);

  add_identity_entry(entries, "historical/G1_V1.2_PROTOCOL.md",
                     historical_evidence / "ANCF_G1_V1.2_PROTOCOL.md",
                     "C8FFC8CCB2D79BC5088EDC2360EB4CA1475053E83652C35D50D2AED32A109DFC");
  add_identity_entry(entries, "historical/G1_V1.2_REPORT.md",
                     historical_evidence / "ANCF_G1_V1.2_REPORT.md",
                     "A8168986BEBEE72E21FC37AB812226297EA65CAB8E6C949C8A653D65601E29D7");
  add_identity_entry(entries, "historical/G1_V1.2_RESULT.json",
                     historical_evidence / "ANCF_G1_V1.2_RESULT.json",
                     "3B6A15C383C67604E2370920C4435025238A091F2BEC8EC2A51F016A944EC9BD");
  add_identity_entry(entries, "historical/G1_V1.2_RAW.txt",
                     historical_evidence / "ANCF_G1_V1.2_RAW.txt",
                     "1A6B6EB862B73D71838A6206394690D5F5E6241B863DAFA74271F153F876FF99");
  add_identity_entry(entries, "historical/G1_V1.2_136_FORENSIC_REPORT.md",
                     historical_evidence / "ANCF_G1_V1.2_136_FAIL_FORENSIC_REPORT_V1.md",
                     "F43393EBA5969BA5217F079853B9E48AA0842E85F4AC9A6BA4EA5824BFC5BDB6");
  add_identity_entry(entries, "historical/G1_V1.2_HARNESS.cpp",
                     historical_evidence / "ancf_g1_v1_2.cpp",
                     "F8CB6F51241E0D9D9D663DF1F412FCD3CE18D02BB26823E6BFFC19353B3AFCF9");

  add_identity_entry(entries, "reference/extensible_cable.md",
                     historical_evidence / "ANCF_G1_EXTENSIBLE_CABLE_REFERENCE_V1.md",
                     "7BF62E578E3CD35CB2F1BC51B09833E40A480542972F0E45BA805C52CB4BB612");
  add_identity_entry(entries, "reference/extensible_cable.json",
                     historical_evidence / "ANCF_G1_EXTENSIBLE_CABLE_REFERENCE_V1.json",
                     "BC221D37D81F71D29B1A42E5D46E1DEDF91BAAA4A7FAB2075BACB8AC9C13983E");
  add_identity_entry(entries, "reference/extensible_cable.csv",
                     historical_evidence / "ANCF_G1_EXTENSIBLE_CABLE_REFERENCE.csv",
                     "713ED565FB67CB22810493BF5DDA9E58934C70BC7980CE7ACA690B0BFE806D32");
  add_identity_entry(entries, "reference/extensible_cable.raw",
                     historical_evidence / "ANCF_G1_EXTENSIBLE_CABLE_REFERENCE_RAW_V1.txt",
                     "D310F770D2BFA6D74E3DD742C3895E6E6C65805EF8C4EA3C8C00B05411DB51B1");
  add_identity_entry(entries, "reference/extensible_cable_source.py",
                     historical_evidence / "ancf_g1_extensible_cable_reference_v1.py",
                     "5DFCD88B58AF8F398A78E0CAE89710158E74EB2C36C2D8C4F2A6AA91D0CC311F");

  add_identity_entry(entries, "preflight/report.md",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_SUCCESSOR_PREFLIGHT_V1_REPORT.md",
                     "3EEA0EDB68E7F40D46FB2A6EDB8E249D5A362C39C11D5C1DA14BDB6F75F40E64");
  add_identity_entry(entries, "preflight/result.json",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_SUCCESSOR_PREFLIGHT_V1_RESULT.json",
                     "74763DCD39DFF18F37FAE583E695FD8FCC963513659C52314BF906F12AA05053");
  add_identity_entry(entries, "preflight/reconstruction.csv",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_SUCCESSOR_PREFLIGHT_V1_RECONSTRUCTION.csv",
                     "DB145B6FAFC91067AC2D2343F3680853C970DECF92C5041FE7D86113944256FC");
  add_identity_entry(entries, "preflight/static_diagnostic_audit.md",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_SUCCESSOR_PREFLIGHT_V1_STATIC_DIAGNOSTIC_AUDIT.md",
                     "6E7FF0887322A6AA5DFDBBE989902A1F861AFFCC9360450BD4CDC6516A553FFA");
  add_identity_entry(entries, "preflight/protocol_draft.md",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_SUCCESSOR_PREFLIGHT_V1_PROTOCOL_DRAFT.md",
                     "C7E84BD4EE5C2700182FE8EF9F8331930EB4C7CC5DECC8E2E3CB87A91BAC3EBF");
  add_identity_entry(entries, "preflight/manifest.txt",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_SUCCESSOR_PREFLIGHT_V1_SHA256_MANIFEST.txt",
                     "9B30C910B15A8414E16465EF9517307385317A177A3A995A1D33738B66E6C36F");

  add_identity_entry(entries, "formal/V1_PROTOCOL.md",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_PROTOCOL.md",
                     "ED38E78678EE3E36D0945EB6F7A286213E670085863DD7E0F474F4ECDFC3071F");
  add_identity_entry(entries, "formal/V1_REPORT.md",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_REPORT.md",
                     "C61D461DF7D2EEAEAC5CE4DCB360CF9E8324C0D18DF397C7759FD5E427374ADF");
  add_identity_entry(entries, "formal/V1_RESULT.json",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_RESULT.json",
                     "CD1B6F76F60E18AC03B94A39C0DB8DBD4FD7432AE55569C80D336F992305D869");
  add_identity_entry(entries, "formal/V1_RAW.txt",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_RAW.txt",
                     "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855");
  add_identity_entry(entries, "formal/V1_MESH.csv",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_MESH.csv",
                     "F1603C0F3129A0AC1CB35FD82EF8B621E681364D57AE3722EE93333C8040E18E");
  add_identity_entry(entries, "formal/V1_OBSERVABLES.csv",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_OBSERVABLES.csv",
                     "E0AD81D65C0A471C0248EF0F95B1428B00EAEE396D0BE5F76A6E1705434DF042");
  add_identity_entry(entries, "formal/V1_DIAGNOSTICS.csv",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_DIAGNOSTICS.csv",
                     "F53C97C1D9EE23C66888ACE69723372B61BC36EF0C9D4D350FC702BF620FAF2E");
  add_identity_entry(entries, "formal/V1_LINE_SEARCH_TRACE.csv",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_LINE_SEARCH_TRACE.csv",
                     "0FECD159A2FF65CE64B6BE5483DB07993D66B34A16C2B52B5B2B81E5AC8C3B4A");
  add_identity_entry(entries, "formal/V1_INITIAL_STATE_IDENTITY.json",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_INITIAL_STATE_IDENTITY.json",
                     "C645EF614B699D10DF3E9AE7D5623F58E658C82D61E44CE8404D12FDD707C654");
  add_identity_entry(entries, "formal/V1_MANIFEST.txt",
                     current_evidence / "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_SHA256_MANIFEST.txt",
                     "291997D1BC9370DDAD06430B891E32320BAE4003FB883BCE6439C5EE95010C43");

  add_identity_entry(entries, "candidate_a/patch_protocol.md",
                     historical_evidence / "ANCF_STATIC_STABLE_POTENTIAL_INCREMENT_PATCH_PROTOCOL_V1.md",
                     "A1DB4D07C42E0BFEF0EFF39ECC197E04D141FD702021F313598A76E8AA7F56E1");
  add_identity_entry(entries, "candidate_a/patch_result.json",
                     historical_evidence / "ANCF_STATIC_STABLE_POTENTIAL_INCREMENT_PATCH_RESULT_V1.json",
                     "2AE7CC7572C8F743FD3994AE09156226CAF7FCC00A414A903E3833B390C895A0");
  add_identity_entry(entries, "candidate_a/regression_protocol.md",
                     historical_evidence / "ANCF_STATIC_STABLE_POTENTIAL_INCREMENT_REGRESSION_PROTOCOL_V1.md",
                     "2FCE06C16EDADF1EFC2667D73FE9EEE8504DEBD0EAA0E47047079ECE8AFB8E13");
  add_identity_entry(entries, "candidate_a/regression_result.json",
                     historical_evidence / "ANCF_STATIC_STABLE_POTENTIAL_INCREMENT_REGRESSION_RESULT_V1.json",
                     "81FC23AAAC59434D4F30AE82494DA45BCC8CF2D3749AE27273DEA7516AA46E53");
  return entries;
}

int run_identity_only() {
  const std::string head = git_head();
  const std::string parent = git_parent();
  const bool git_pass = head == kCommit && parent == kParent;
  const auto entries = required_identity_entries();
  bool all_pass = git_pass;
  std::cout << std::setprecision(17);
  std::cout << "{\"schema_version\":\"ancf_g1_v1_1_identity_only.1\""
            << ",\"terminal_marker\":\"STOP_BEFORE_G1_NUMERICAL_EXECUTION\""
            << ",\"head\":\"" << json_escape(head) << "\""
            << ",\"parent\":\"" << json_escape(parent) << "\""
            << ",\"git_identity_pass\":" << (git_pass ? "true" : "false")
            << ",\"meshes_executed\":[]"
            << ",\"static_solve_calls\":0"
            << ",\"newton_iterations\":0"
            << ",\"line_search_trials\":0"
            << ",\"identity_files\":[";
  for (std::size_t i = 0; i < entries.size(); ++i) {
    if (i) std::cout << ',';
    const auto& entry = entries[i];
    const bool exists = std::filesystem::is_regular_file(entry.path);
    std::uintmax_t size = 0;
    std::string actual;
    std::string error;
    if (exists) {
      std::error_code size_error;
      size = std::filesystem::file_size(entry.path, size_error);
      if (size_error) error = "file_size_failed";
      try {
        actual = sha256_file(entry.path);
      } catch (const std::exception& exception) {
        error = exception.what();
      }
    } else {
      error = "file_not_found";
    }
    const bool pass = exists && error.empty() && actual == entry.expected_sha256;
    all_pass = all_pass && pass;
    std::cout << "{\"logical_name\":\"" << json_escape(entry.logical_name)
              << "\",\"resolved_path\":\"" << json_escape(path_utf8(entry.path))
              << "\",\"open_status\":\"" << (exists ? "OPEN" : "NOT_OPEN")
              << "\",\"size_bytes\":" << size
              << ",\"actual_sha256\":\"" << json_escape(actual)
              << "\",\"expected_sha256\":\""
              << json_escape(entry.expected_sha256)
              << "\",\"identity\":\"" << (pass ? "PASS" : "FAIL")
              << "\",\"error\":\"" << json_escape(error) << "\"}";
  }
  std::cout << "],\"all_required_artifacts_pass\":"
            << (all_pass ? "true" : "false")
            << ",\"scientific_contract_invariance\":\"UNCHANGED\""
            << ",\"numerical_execution\":false"
            << ",\"production_numerical_api_called\":false"
            << ",\"G1_model_constructed\":false"
            << ",\"reference_interpolated\":false"
            << ",\"status\":\"" << (all_pass ? "PASS" : "FAIL") << "\"}\n";
  return all_pass ? 0 : 4;
}
double dot3(const Vec3& a, const Vec3& b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

Vec3 cross3(const Vec3& a, const Vec3& b) {
  return {a[1] * b[2] - a[2] * b[1],
          a[2] * b[0] - a[0] * b[2],
          a[0] * b[1] - a[1] * b[0]};
}

double norm3(const Vec3& a) {
  return std::sqrt(dot3(a, a));
}

bool finite_vector(const std::vector<double>& values) {
  return std::all_of(values.begin(), values.end(),
                     [](double value) { return std::isfinite(value); });
}

struct RefRow {
  double S = 0.0;
  double x = 0.0;
  double z = 0.0;
  double lambda = 1.0;
  double theta = 0.0;
};

class ExtensibleReference {
 public:
  explicit ExtensibleReference(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("cannot open extensible reference CSV");
    std::string line;
    if (!std::getline(input, line)) throw std::runtime_error("empty reference CSV");
    while (std::getline(input, line)) {
      if (line.empty()) continue;
      std::stringstream stream(line);
      std::string field;
      std::vector<double> values;
      while (std::getline(stream, field, ',')) values.push_back(std::stod(field));
      if (values.size() < 8) throw std::runtime_error("malformed extensible reference row");
      rows_.push_back({values[0], values[1], values[2], values[5], values[7]});
    }
    if (rows_.size() < 2 || rows_.front().S > 1.0e-12 ||
        std::abs(rows_.back().S - kL0) > 1.0e-9) {
      throw std::runtime_error("extensible reference domain is invalid");
    }
  }

  RefRow at(double S) const {
    if (S <= rows_.front().S) return rows_.front();
    if (S >= rows_.back().S) return rows_.back();
    auto upper = std::upper_bound(
        rows_.begin(), rows_.end(), S,
        [](double value, const RefRow& row) { return value < row.S; });
    const RefRow& hi = *upper;
    const RefRow& lo = *(upper - 1);
    const double t = (S - lo.S) / (hi.S - lo.S);
    return {
        lo.S + t * (hi.S - lo.S),
        lo.x + t * (hi.x - lo.x),
        lo.z + t * (hi.z - lo.z),
        lo.lambda + t * (hi.lambda - lo.lambda),
        lo.theta + t * (hi.theta - lo.theta)};
  }

 private:
  std::vector<RefRow> rows_;
};

struct PointValue {
  Vec3 r{0.0, 0.0, 0.0};
  Vec3 rs{0.0, 0.0, 0.0};
  Vec3 rss{0.0, 0.0, 0.0};
  double epsilon = 0.0;
  double kappa_x = 0.0;
  double theta = 0.0;
};

std::array<double, 4> hermite_shape(double x, double length, int derivative) {
  const double xi = x / length;
  const double xi2 = xi * xi;
  const double xi3 = xi2 * xi;
  const double length2 = length * length;
  if (derivative == 0)
    return {1.0 - 3.0 * xi2 + 2.0 * xi3,
            length * (xi - 2.0 * xi2 + xi3),
            3.0 * xi2 - 2.0 * xi3,
            length * (-xi2 + xi3)};
  if (derivative == 1)
    return {(6.0 * xi2 - 6.0 * xi) / length,
            1.0 - 4.0 * xi + 3.0 * xi2,
            (-6.0 * xi2 + 6.0 * xi) / length,
            -2.0 * xi + 3.0 * xi2};
  if (derivative == 2)
    return {(12.0 * xi - 6.0) / length2,
            (-4.0 + 6.0 * xi) / length,
            (6.0 - 12.0 * xi) / length2,
            (-2.0 + 6.0 * xi) / length};
  throw std::invalid_argument("unsupported Hermite derivative");
}

PointValue evaluate_point(const std::vector<double>& q,
                          const cfd_ancf::Model& model, double S) {
  const double Le = model.length_m / static_cast<double>(model.elements);
  const std::size_t element =
      S >= model.length_m
          ? model.elements - 1
          : std::min(model.elements - 1,
                     static_cast<std::size_t>(std::floor(S / Le)));
  const double x = S - static_cast<double>(element) * Le;
  const auto N = hermite_shape(x, Le, 0);
  const auto A = hermite_shape(x, Le, 1);
  const auto B = hermite_shape(x, Le, 2);
  PointValue point;
  for (int block = 0; block < 4; ++block) {
    for (int component = 0; component < 3; ++component) {
      const std::size_t index = 6 * element + 3 * block +
                                static_cast<std::size_t>(component);
      point.r[component] += N[block] * q[index];
      point.rs[component] += A[block] * q[index];
      point.rss[component] += B[block] * q[index];
    }
  }
  const double rs2 = dot3(point.rs, point.rs);
  const double rs_norm = std::sqrt(rs2);
  const Vec3 cross_value = cross3(point.rs, point.rss);
  point.epsilon = 0.5 * (rs2 - 1.0);
  point.kappa_x = cross_value[0] / (rs2 * rs_norm);
  point.theta = std::atan2(point.rs[0] * 0.0 + point.rs[1], point.rs[2]);
  return point;
}

struct EnergyMetrics {
  double axial = 0.0;
  double bending = 0.0;
  double total = 0.0;
  double arc_length = 0.0;
  double delta_L = 0.0;
  double max_abs_green_strain = 0.0;
};

EnergyMetrics independent_energy(const std::vector<double>& q,
                                 const cfd_ancf::Model& model) {
  constexpr std::array<double, 5> xi{
      -0.9061798459386639928, -0.5384693101056830910, 0.0,
       0.5384693101056830910, 0.9061798459386639928};
  constexpr std::array<double, 5> weights{
      0.2369268850561890875, 0.4786286704993664700,
      0.5688888888888888889, 0.4786286704993664700,
      0.2369268850561890875};
  const double Le = model.length_m / static_cast<double>(model.elements);
  EnergyMetrics result;
  for (std::size_t element = 0; element < model.elements; ++element) {
    for (std::size_t k = 0; k < xi.size(); ++k) {
      const double x = 0.5 * (xi[k] + 1.0) * Le;
      const PointValue point = evaluate_point(
          q, model, static_cast<double>(element) * Le + x);
      const double rs2 = dot3(point.rs, point.rs);
      const double rs_norm = std::sqrt(rs2);
      const Vec3 cross_value = cross3(point.rs, point.rss);
      const double kappa2 =
          dot3(cross_value, cross_value) / (rs2 * rs2 * rs2);
      const double weight = weights[k] * Le / 2.0;
      result.axial += 0.5 * model.EA() * point.epsilon * point.epsilon * weight;
      result.bending += 0.5 * model.EI() * kappa2 * weight;
      result.arc_length += rs_norm * weight;
      result.delta_L += (rs_norm - 1.0) * weight;
      result.max_abs_green_strain =
          (std::max)(result.max_abs_green_strain, std::abs(point.epsilon));
    }
  }
  result.total = result.axial + result.bending;
  return result;
}

cfd_ancf::Model make_model(std::size_t elements) {
  cfd_ancf::Model model;
  model.length_m = kL0;
  model.diameter_m = kDEff;
  model.inner_diameter_m = 0.0;
  model.elements = elements;
  model.slices = 1;
  model.slice_positions_m.clear();
  model.top_tension_N = 0.0;
  model.youngs_modulus_Pa = kEEff;
  model.material_density = kRhoMEff;
  model.fluid_density = kRhoFEff;
  model.gravity = kGravity;
  model.include_gravity = true;
  model.include_buoyancy = true;
  model.dt_s = 0.00125;
  model.beta = 0.25;
  model.gamma = 0.5;
  model.max_newton = kMaxNewton;
  model.newton_tolerance = kNewtonTolerance;
  model.damping_alpha = 0.0;
  model.damping_beta = 0.0;
  model.gauss_order = kGaussOrder;
  model.mass_gauss_order = kMassGaussOrder;
  const std::size_t top = 6 * elements;
  model.fixed_dof = {0, 1, 2, top, top + 1, top + 2};
  model.prescribed_values = {0.0, 0.0, 0.0, kXTarget, 0.0, kZTarget};
  model.boundary_contract_id = kBoundaryId;
  return model;
}

std::vector<double> stress_compatible_q0(const cfd_ancf::Model& model,
                                         const ExtensibleReference& reference) {
  std::vector<double> q(model.ndof(), 0.0);
  const double Le = model.length_m / static_cast<double>(model.elements);
  for (std::size_t node = 0; node <= model.elements; ++node) {
    const double S = static_cast<double>(node) * Le;
    const RefRow row = reference.at(S);
    const std::size_t base = 6 * node;
    q[base + 0] = row.x;
    q[base + 1] = 0.0;
    q[base + 2] = row.z;
    q[base + 3] = row.lambda * std::cos(row.theta);
    q[base + 4] = 0.0;
    q[base + 5] = row.lambda * std::sin(row.theta);
  }
  q[0] = 0.0;
  q[1] = 0.0;
  q[2] = 0.0;
  const std::size_t top = 6 * model.elements;
  q[top + 0] = kXTarget;
  q[top + 1] = 0.0;
  q[top + 2] = kZTarget;
  return q;
}

struct Reaction {
  Vec3 lower{0.0, 0.0, 0.0};
  Vec3 upper{0.0, 0.0, 0.0};
  double lower_tension = 0.0;
  double upper_tension = 0.0;
};

Reaction endpoint_reactions(const std::vector<double>& internal,
                            const std::vector<double>& base_load,
                            std::size_t elements) {
  const std::size_t top = 6 * elements;
  Reaction result;
  for (std::size_t c = 0; c < 3; ++c) {
    result.lower[c] = internal[c] - base_load[c];
    result.upper[c] = internal[top + c] - base_load[top + c];
  }
  result.lower_tension =
      std::hypot(result.lower[0], result.lower[2]);
  result.upper_tension =
      std::hypot(result.upper[0], result.upper[2]);
  return result;
}

double free_residual_inf(const std::vector<double>& q,
                         const cfd_ancf::Model& model,
                         const std::vector<double>& base_load,
                         std::vector<double>* internal_out = nullptr) {
  std::vector<double> internal;
  Matrix tangent;
  cfd_ancf::internal_force_tangent(q, model, internal, tangent);
  if (internal_out) *internal_out = internal;
  std::vector<char> fixed(model.ndof(), 0);
  for (std::size_t index : model.fixed_dof) fixed[index] = 1;
  double result = 0.0;
  for (std::size_t index = 0; index < model.ndof(); ++index) {
    if (!fixed[index])
      result = (std::max)(result, std::abs(internal[index] - base_load[index]));
  }
  return result;
}

bool trace_contract(const cfd_ancf::StepDiagnostics& diagnostics,
                    std::string& reason) {
  for (const auto& iteration : diagnostics.static_newton_trace) {
    if (!iteration.finite ||
        !std::isfinite(iteration.residual_before_step) ||
        !std::isfinite(iteration.residual_normalized_before_step) ||
        !std::isfinite(iteration.full_newton_direction_norm) ||
        !std::isfinite(iteration.r_dot_p) ||
        !std::isfinite(iteration.internal_energy_before)) {
      reason = "non-finite iteration diagnostic";
      return false;
    }
    if (iteration.line_search_failed) {
      if (iteration.trials.size() != kBetaCount) {
        reason = "line-search failure trace does not contain 13 trials";
        return false;
      }
      for (std::size_t k = 0; k < kBetaCount; ++k) {
        if (iteration.trials[k].beta != std::ldexp(1.0, -static_cast<int>(k))) {
          reason = "line-search beta sequence violation";
          return false;
        }
      }
      continue;
    }
    if (iteration.trials.empty()) {
      if (iteration.beta_accepted != 0.0) {
        reason = "empty trial list has a nonzero accepted beta";
        return false;
      }
      continue;
    }
    if (!(iteration.r_dot_p < 0.0) ||
        iteration.backtrack_count >= iteration.trials.size() ||
        iteration.backtrack_count > 12 ||
        iteration.trials.size() != iteration.backtrack_count + 1) {
      reason = "potential accepted-step contract violation";
      return false;
    }
    for (std::size_t k = 0; k < iteration.trials.size(); ++k) {
      const auto& trial = iteration.trials[k];
      const double expected = std::ldexp(1.0, -static_cast<int>(k));
      if (trial.beta != expected || !trial.finite ||
          !std::isfinite(trial.delta_potential) ||
          !std::isfinite(trial.armijo_rhs) ||
          trial.r_dot_p != iteration.r_dot_p ||
          trial.r_dot_p >= 0.0) {
        reason = "potential trial contract violation";
        return false;
      }
    }
    const auto& selected = iteration.trials[iteration.backtrack_count];
    if (selected.beta != iteration.beta_accepted ||
        !(selected.convergence_pass || selected.sufficient_decrease)) {
      reason = "accepted potential trial does not satisfy acceptance";
      return false;
    }
    if (!selected.convergence_pass &&
        selected.delta_potential >
            kC1 * selected.beta * iteration.r_dot_p) {
      reason = "accepted non-converged trial violates Armijo";
      return false;
    }
  }
  if (diagnostics.static_newton_trace.empty() && !diagnostics.converged) {
    reason = "missing potential trace";
    return false;
  }
  return true;
}

struct CaseResult {
  std::size_t elements = 0;
  bool finite = false;
  bool converged = false;
  bool trace_contract = false;
  std::string failure_reason;
  double production_initial_residual = 0.0;
  double production_final_residual = 0.0;
  double production_residual_scale = 0.0;
  double production_terminal_normalized_residual = 0.0;
  std::size_t production_iterations = 0;
  double post_call_state_residual = 0.0;
  double post_call_state_normalized = 0.0;
  double lower_endpoint_error = 0.0;
  double upper_endpoint_error = 0.0;
  double max_abs_global_y = 0.0;
  EnergyMetrics energy;
  Reaction reaction;
  std::vector<double> target_errors;
  double E_target = std::numeric_limits<double>::quiet_NaN();
  std::vector<PointValue> centerline;
  cfd_ancf::StepDiagnostics diagnostics;
};

bool all_finite_case_values(const CaseResult& value) {
  return std::isfinite(value.production_initial_residual) &&
         std::isfinite(value.production_final_residual) &&
         std::isfinite(value.production_residual_scale) &&
         std::isfinite(value.production_terminal_normalized_residual) &&
         std::isfinite(value.post_call_state_residual) &&
         std::isfinite(value.post_call_state_normalized) &&
         std::isfinite(value.lower_endpoint_error) &&
         std::isfinite(value.upper_endpoint_error) &&
         std::isfinite(value.max_abs_global_y) &&
         std::isfinite(value.energy.axial) &&
         std::isfinite(value.energy.bending) &&
         std::isfinite(value.energy.total) &&
         std::isfinite(value.energy.arc_length) &&
         std::isfinite(value.energy.delta_L) &&
         std::isfinite(value.energy.max_abs_green_strain);
}

CaseResult run_case(std::size_t elements,
                    const ExtensibleReference& reference) {
  CaseResult result;
  result.elements = elements;
  const cfd_ancf::Model model = make_model(elements);
  const std::vector<double> q0 = stress_compatible_q0(model, reference);
  const std::vector<double> base_load = cfd_ancf::static_base_load(model);
  cfd_ancf::State state = cfd_ancf::make_reference_state(model);
  state.q = q0;
  cfd_ancf::StepDiagnostics diagnostics;
  bool threw = false;
  try {
    diagnostics = cfd_ancf::static_equilibrium(
        state, model, base_load, 1,
        cfd_ancf::StaticSolverMode::PotentialBacktrackingNewton,
        cfd_ancf::StaticLoadContract::FixedConservativeGeneralizedLoad);
  } catch (const std::exception& error) {
    threw = true;
    result.failure_reason = error.what();
  }
  if (!threw) {
    result.diagnostics = diagnostics;
    result.production_initial_residual = diagnostics.initial_residual;
    result.production_final_residual = diagnostics.residual;
    result.production_residual_scale = diagnostics.residual_scale;
    if (diagnostics.residual_scale > 0.0 &&
        std::isfinite(diagnostics.residual_scale)) {
      result.production_terminal_normalized_residual =
          diagnostics.residual / diagnostics.residual_scale;
    }
    result.production_iterations = diagnostics.iterations;
    result.converged = diagnostics.converged;
    if (!diagnostics.converged && result.failure_reason.empty())
      result.failure_reason = diagnostics.failure_reason;
  } else {
    result.converged = false;
  }

  // On failed static_equilibrium(), state.q is not the working Newton state;
  // retain this only as an explicitly labeled post-call stale-state diagnostic.
  std::vector<double> internal;
  result.post_call_state_residual =
      free_residual_inf(state.q, model, base_load, &internal);
  double external_scale = 1.0;
  for (std::size_t index = 0; index < model.ndof(); ++index) {
    bool fixed = false;
    for (std::size_t fixed_index : model.fixed_dof)
      if (fixed_index == index) fixed = true;
    if (!fixed) external_scale =
        (std::max)(external_scale, std::abs(base_load[index]));
  }
  result.post_call_state_normalized =
      result.post_call_state_residual / external_scale;
  result.reaction = endpoint_reactions(internal, base_load, elements);

  const std::size_t top = 6 * elements;
  const Vec3 lower{state.q[0], state.q[1], state.q[2]};
  const Vec3 upper{state.q[top], state.q[top + 1], state.q[top + 2]};
  result.lower_endpoint_error = norm3(lower) / kL0;
  result.upper_endpoint_error =
      std::sqrt((upper[0] - kXTarget) * (upper[0] - kXTarget) +
                upper[1] * upper[1] +
                (upper[2] - kZTarget) * (upper[2] - kZTarget)) / kL0;
  result.energy = independent_energy(state.q, model);
  result.centerline.reserve(kCenterlineSamples);
  for (std::size_t i = 0; i < kCenterlineSamples; ++i) {
    const double S = kL0 * static_cast<double>(i) /
                     static_cast<double>(kCenterlineSamples - 1);
    PointValue point = evaluate_point(state.q, model, S);
    result.max_abs_global_y =
        (std::max)(result.max_abs_global_y, std::abs(point.r[1]));
    result.centerline.push_back(point);
  }
  result.finite =
      cfd_ancf::finite(state) && finite_vector(internal) &&
      all_finite_case_values(result) &&
      std::all_of(result.centerline.begin(), result.centerline.end(),
                  [](const PointValue& point) {
                    return std::isfinite(point.r[0]) &&
                           std::isfinite(point.r[1]) &&
                           std::isfinite(point.r[2]) &&
                           std::isfinite(point.epsilon) &&
                           std::isfinite(point.kappa_x) &&
                           std::isfinite(point.theta);
                  });
  if (!threw) {
    result.trace_contract = trace_contract(diagnostics, result.failure_reason);
  }

  const std::array<double, 6> values{
      result.reaction.upper_tension, result.reaction.lower_tension,
      std::abs(result.reaction.upper[2]), std::abs(result.reaction.upper[0]),
      std::abs(result.reaction.lower[2]), std::abs(result.reaction.lower[0])};
  result.target_errors.resize(6);
  double square_sum = 0.0;
  for (std::size_t i = 0; i < values.size(); ++i) {
    result.target_errors[i] =
        std::abs(values[i] - kTargets[i]) / kTargets[i];
    square_sum += result.target_errors[i] * result.target_errors[i];
  }
  result.E_target = std::sqrt(square_sum / 6.0);
  if (!std::isfinite(result.E_target) ||
      !std::all_of(result.target_errors.begin(), result.target_errors.end(),
                   [](double value) { return std::isfinite(value); })) {
    result.finite = false;
  }
  return result;
}

bool mesh_pass(const CaseResult& value) {
  return value.finite && value.converged && value.trace_contract &&
         value.production_terminal_normalized_residual <= 1.0e-8 &&
         value.lower_endpoint_error <= 1.0e-8 &&
         value.upper_endpoint_error <= 1.0e-8;
}

bool primary_pass(const CaseResult& value) {
  const bool signs = value.reaction.lower[0] < 0.0 &&
                     value.reaction.lower[2] > 0.0 &&
                     value.reaction.upper[0] > 0.0 &&
                     value.reaction.upper[2] > 0.0;
  const bool targets = value.target_errors.size() == 6 &&
      std::all_of(value.target_errors.begin(), value.target_errors.end(),
                  [](double error) { return error <= 0.01; });
  return mesh_pass(value) && signs && targets;
}

void write_centerline(const CaseResult& value) {
  const std::string path =
      "ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_CENTERLINE_" +
      std::to_string(value.elements) + ".csv";
  std::ofstream output(path, std::ios::binary);
  if (!output) throw std::runtime_error("cannot open G1-V1.2 centerline CSV");
  output << std::setprecision(17);
  output << "elements,S_m,x_m,y_m,z_m,theta_FE_rad,green_strain,kappa_x_1pm\n";
  for (std::size_t i = 0; i < value.centerline.size(); ++i) {
    const auto& point = value.centerline[i];
    const double S = kL0 * static_cast<double>(i) /
                     static_cast<double>(value.centerline.size() - 1);
    output << value.elements << ',' << S << ','
           << point.r[0] << ',' << point.r[1] << ',' << point.r[2] << ','
           << point.theta << ',' << point.epsilon << ',' << point.kappa_x << '\n';
  }
}

void print_vec3(std::ostream& out, const Vec3& value) {
  out << '[' << value[0] << ',' << value[1] << ',' << value[2] << ']';
}

void print_diagnostics(std::ostream& out,
                       const cfd_ancf::StepDiagnostics& diagnostics) {
  out << "{\"initial_residual\":" << diagnostics.initial_residual
      << ",\"residual\":" << diagnostics.residual
      << ",\"residual_scale\":" << diagnostics.residual_scale
      << ",\"terminal_normalized_residual\":"
      << (diagnostics.residual_scale > 0.0
              ? diagnostics.residual / diagnostics.residual_scale
              : std::numeric_limits<double>::quiet_NaN())
      << ",\"iterations\":" << diagnostics.iterations
      << ",\"converged\":" << (diagnostics.converged ? "true" : "false")
      << ",\"failure_reason\":\"" << diagnostics.failure_reason << "\""
      << ",\"trace\":[";
  for (std::size_t i = 0; i < diagnostics.static_newton_trace.size(); ++i) {
    if (i) out << ',';
    const auto& iteration = diagnostics.static_newton_trace[i];
    out << "{\"load_step\":" << iteration.load_step
        << ",\"iteration\":" << iteration.iteration
        << ",\"residual_before\":" << iteration.residual_before_step
        << ",\"residual_normalized_before\":"
        << iteration.residual_normalized_before_step
        << ",\"full_newton_direction_norm\":"
        << iteration.full_newton_direction_norm
        << ",\"R_dot_p\":" << iteration.r_dot_p
        << ",\"internal_energy_before\":"
        << iteration.internal_energy_before
        << ",\"beta_accepted\":" << iteration.beta_accepted
        << ",\"backtrack_count\":" << iteration.backtrack_count
        << ",\"delta_potential_accepted\":"
        << iteration.delta_potential_accepted
        << ",\"residual_after\":" << iteration.residual_after_accepted_trial
        << ",\"residual_normalized_after\":"
        << iteration.residual_normalized_after_accepted_trial
        << ",\"finite\":" << (iteration.finite ? "true" : "false")
        << ",\"line_search_failed\":"
        << (iteration.line_search_failed ? "true" : "false")
        << ",\"trials\":[";
    for (std::size_t j = 0; j < iteration.trials.size(); ++j) {
      if (j) out << ',';
      const auto& trial = iteration.trials[j];
      out << "{\"beta\":" << trial.beta
          << ",\"residual\":" << trial.residual
          << ",\"merit\":" << trial.merit
          << ",\"internal_energy\":" << trial.internal_energy
          << ",\"delta_potential\":" << trial.delta_potential
          << ",\"armijo_rhs\":" << trial.armijo_rhs
          << ",\"R_dot_p\":" << trial.r_dot_p
          << ",\"finite\":" << (trial.finite ? "true" : "false")
          << ",\"convergence_pass\":"
          << (trial.convergence_pass ? "true" : "false")
          << ",\"sufficient_decrease\":"
          << (trial.sufficient_decrease ? "true" : "false") << '}';
    }
    out << "]}";
  }
  out << "]}";
}

void print_case(std::ostream& out, const CaseResult& value) {
  out << "{\"elements\":" << value.elements
      << ",\"finite\":" << (value.finite ? "true" : "false")
      << ",\"converged\":" << (value.converged ? "true" : "false")
      << ",\"trace_contract\":"
      << (value.trace_contract ? "true" : "false")
      << ",\"failure_reason\":\"" << value.failure_reason << "\""
      << ",\"production_initial_residual\":"
      << value.production_initial_residual
      << ",\"production_final_residual\":"
      << value.production_final_residual
      << ",\"production_residual_scale\":"
      << value.production_residual_scale
      << ",\"production_terminal_normalized_residual\":"
      << value.production_terminal_normalized_residual
      << ",\"production_iterations\":" << value.production_iterations
      << ",\"post_call_state_residual\":"
      << value.post_call_state_residual
      << ",\"post_call_state_normalized\":"
      << value.post_call_state_normalized
      << ",\"endpoint_lower_error_normalized\":"
      << value.lower_endpoint_error
      << ",\"endpoint_upper_error_normalized\":"
      << value.upper_endpoint_error
      << ",\"max_abs_global_y_m\":" << value.max_abs_global_y
      << ",\"current_geometric_arc_length_m\":" << value.energy.arc_length
      << ",\"delta_L_m\":" << value.energy.delta_L
      << ",\"max_abs_green_strain\":"
      << value.energy.max_abs_green_strain
      << ",\"axial_strain_energy_J\":" << value.energy.axial
      << ",\"bending_energy_J\":" << value.energy.bending
      << ",\"total_strain_energy_J\":" << value.energy.total
      << ",\"lower_reaction_N\":";
  print_vec3(out, value.reaction.lower);
  out << ",\"upper_reaction_N\":";
  print_vec3(out, value.reaction.upper);
  out << ",\"lower_effective_tension_N\":"
      << value.reaction.lower_tension
      << ",\"upper_effective_tension_N\":"
      << value.reaction.upper_tension
      << ",\"target_relative_errors\":[";
  for (std::size_t i = 0; i < value.target_errors.size(); ++i) {
    if (i) out << ',';
    out << value.target_errors[i];
  }
  out << "],\"E_target\":" << value.E_target
      << ",\"diagnostics\":";
  print_diagnostics(out, value.diagnostics);
  out << '}';
}

void write_mesh_snapshot(const CaseResult& value) {
  const std::string path =
      "runtime/ANCF_validation/ANCF_G1_LOW_LANGLEY_CURRENT_LINE_VALIDATION_V1_MESH_" +
      std::to_string(value.elements) + "_SNAPSHOT.json";
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  if (!output) throw std::runtime_error("cannot serialize mesh evidence snapshot");
  output << std::setprecision(17);
  output << "{\"schema_version\":\"ancf_g1_current_line_v1.mesh_snapshot.1\""
         << ",\"mesh\":" << value.elements << ",\"evidence_before_gate\":true"
         << ",\"case\":";
  print_case(output, value);
  output << "}\n";
  output.flush();
  if (!output) throw std::runtime_error("mesh evidence snapshot flush failed");
}

void print_result(std::ostream& out, const std::vector<CaseResult>& cases,
                  bool primary, bool all_mesh, bool trend) {
  const bool pass = primary && all_mesh && trend;
  out << "{\"schema_version\":\"ancf_g1_v1_2.raw.1\""
      << ",\"status\":\"" << (pass ? "PASS" : "FAIL") << "\""
      << ",\"production_commit\":\"" << kCommit << "\""
      << ",\"kernel_sha256\":\"" << kKernelSha << "\""
      << ",\"header_sha256\":\"" << kHeaderSha << "\""
      << ",\"protocol_sha256\":\"" << kProtocolSha << "\""
      << ",\"reference_csv\":\"" << path_utf8(g_evidence_root / kReferenceRelative) << "\""
      << ",\"solver_mode\":\"PotentialBacktrackingNewton\""
      << ",\"load_contract\":\"FixedConservativeGeneralizedLoad\""
      << ",\"load_steps\":1,\"alpha\":1,\"max_newton\":40"
      << ",\"newton_tolerance\":1e-8,\"gauss_order\":3"
      << ",\"mass_gauss_order\":5,\"beta_sequence\":[";
  for (std::size_t k = 0; k < kBetaCount; ++k) {
    if (k) out << ',';
    out << std::ldexp(1.0, -static_cast<int>(k));
  }
  out << "],\"c1\":1e-4"
      << ",\"execution_order\":[68";
  if (cases.size() >= 2) out << ",34";
  if (cases.size() >= 3) out << ",136";
  out << "],\"hard_short_circuit\":true"
      << ",\"primary_68_pass\":" << (primary ? "true" : "false")
      << ",\"all_executed_meshes_pass\":"
      << (all_mesh ? "true" : "false")
      << ",\"E_target_136_lt_E_target_34\":"
      << (trend ? "true" : "false")
      << ",\"cases\":[";
  for (std::size_t i = 0; i < cases.size(); ++i) {
    if (i) out << ',';
    print_case(out, cases[i]);
  }
  out << "],\"G1_numerical_run\":true,\"A_to_F_rerun\":false"
      << ",\"MATLAB_OpenFOAM_preCICE_CFD_FSI\":false}";
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  try {
    const CommandLineOptions options = parse_options(argc, argv);
    g_repo_root = options.repo_root;
    g_evidence_root = options.evidence_root;
    if (options.identity_only) return run_identity_only();
    std::cout << std::setprecision(17);
    identity_checkpoint("before_68");
    const ExtensibleReference reference(g_evidence_root / kReferenceRelative);
    std::vector<CaseResult> cases;

    cases.push_back(run_case(68, reference));
    write_centerline(cases.back());
    write_mesh_snapshot(cases.back());
    identity_checkpoint("after_68");
    const bool p68 = primary_pass(cases.back());
    if (!p68) {
      print_result(std::cout, cases, false, false, false);
      return 3;
    }

    cases.push_back(run_case(34, reference));
    write_centerline(cases.back());
    write_mesh_snapshot(cases.back());
    identity_checkpoint("after_34");
    const bool p34 = mesh_pass(cases.back());
    if (!p34) {
      print_result(std::cout, cases, true, false, false);
      return 3;
    }

    cases.push_back(run_case(136, reference));
    write_centerline(cases.back());
    write_mesh_snapshot(cases.back());
    identity_checkpoint("after_136");
    const bool p136 = mesh_pass(cases.back());
    const bool trend = p136 &&
        cases[2].E_target < cases[1].E_target;
    const bool all_mesh = p34 && p136;
    identity_checkpoint("before_final_result");
    print_result(std::cout, cases, true, all_mesh, trend);
    return (p68 && all_mesh && trend) ? 0 : 3;
  } catch (const std::exception& error) {
    std::cerr << "ANCF_G1_V1.2 exception: " << error.what() << '\n';
    return 2;
  }
}
