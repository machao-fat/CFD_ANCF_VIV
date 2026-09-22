#include "ancf_kernel.hpp"

#include <array>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

namespace {

constexpr double kLength = 10.0;
constexpr std::size_t kElements = 11;

struct ExactLoad {
  std::array<double, 3> operator()(const std::string& case_id, double s) const {
    if (case_id == "case_a_sinusoidal") {
      return {
          1.25 + 0.37 * std::sin(0.43 * s) + 0.23 * std::cos(0.71 * s),
          -0.42 + 0.29 * std::sin(0.37 * s + 0.23),
          0.31 + 0.11 * std::cos(0.29 * s + 0.17),
      };
    }
    if (case_id == "case_b_mixed_smooth") {
      return {
          0.80 + 0.45 * std::exp(0.12 * s / kLength) +
              0.18 * std::sin(0.63 * s + 0.11),
          -0.35 + 0.22 * std::cos(0.51 * s + 0.37),
          0.25 + 0.14 * std::exp(-0.08 * s / kLength) +
              0.09 * std::sin(0.27 * s + 0.19),
      };
    }
    if (case_id == "exact_linear_sanity") {
      return {0.80 + 0.13 * s, -0.40 + 0.07 * s, 0.20 - 0.05 * s};
    }
    throw std::runtime_error("unknown exact-load case");
  }
};

std::vector<double> sample_positions(std::size_t count, bool nonuniform) {
  std::vector<double> result;
  result.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    const double xi = static_cast<double>(index) / static_cast<double>(count - 1);
    const double mapped = nonuniform
        ? xi + 0.20 * std::sin(2.0 * 3.1415926535897932384626433832795 * xi) /
                  (2.0 * 3.1415926535897932384626433832795)
        : xi;
    result.push_back(kLength * mapped);
  }
  return result;
}

cfd_ancf::Model make_model(const std::vector<double>& positions) {
  cfd_ancf::Model model;
  model.length_m = kLength;
  model.diameter_m = 1.0;
  model.inner_diameter_m = 0.9;
  model.elements = kElements;
  model.slices = positions.size();
  model.slice_positions_m = positions;
  model.top_tension_N = 0.0;
  model.gravity = 0.0;
  model.include_gravity = true;
  model.include_buoyancy = true;
  model.spanwise_load_reconstruction =
      cfd_ancf::SpanwiseLoadReconstruction::PiecewiseLinearDistributed;
  model.spanwise_endpoint_policy = cfd_ancf::SpanwiseEndpointPolicy::NearestConstant;
  model.spanwise_active_s_min_m = 0.0;
  model.spanwise_active_s_max_m = kLength;
  cfd_ancf::validate_model(model);
  return model;
}

void print_vector(const std::vector<double>& values) {
  std::cout << '[';
  for (std::size_t index = 0; index < values.size(); ++index) {
    if (index != 0) std::cout << ',';
    std::cout << std::setprecision(17) << values[index];
  }
  std::cout << ']';
}

void emit(const std::string& case_id, const std::string& family,
          std::size_t sample_count, bool nonuniform) {
  const auto positions = sample_positions(sample_count, nonuniform);
  const auto model = make_model(positions);
  const ExactLoad exact;
  cfd_ancf::SpanwiseLoadInput input;
  input.mode = cfd_ancf::SpanwiseLoadReconstruction::PiecewiseLinearDistributed;
  input.endpoint_policy = cfd_ancf::SpanwiseEndpointPolicy::NearestConstant;
  input.active_region = {0.0, kLength};
  for (double position : positions)
    input.samples.push_back({position, exact(case_id, position)});
  const auto generalized_load = cfd_ancf::external_force(model, input);
  std::cout << "{\"case_id\":\"" << case_id
            << "\",\"family\":\"" << family
            << "\",\"mode\":\"PiecewiseLinearDistributed\""
            << ",\"Ns\":" << sample_count
            << ",\"L\":" << std::setprecision(17) << kLength
            << ",\"elements\":" << kElements << ",\"q\":";
  print_vector(generalized_load);
  std::cout << "}\n";
}

}  // namespace

int main() {
  try {
    for (const std::string case_id : {"case_a_sinusoidal", "case_b_mixed_smooth"}) {
      for (const std::size_t count : {std::size_t(5), std::size_t(9),
                                      std::size_t(17), std::size_t(33), std::size_t(65)}) {
        emit(case_id, "uniform", count, false);
        emit(case_id, "nonuniform", count, true);
      }
    }
    emit("exact_linear_sanity", "uniform", 5, false);
  } catch (const std::exception& error) {
    std::cerr << "SPANWISE_CONVERGENCE_EXCEPTION=" << error.what() << '\n';
    return 1;
  }
  return 0;
}
