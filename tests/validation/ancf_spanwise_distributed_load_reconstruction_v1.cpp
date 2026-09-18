#include "ancf_kernel.hpp"

#include <array>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

namespace {

cfd_ancf::Model test_model(std::size_t elements, double length) {
  cfd_ancf::Model model;
  model.length_m = length;
  model.diameter_m = 1.0;
  model.inner_diameter_m = 0.9;
  model.elements = elements;
  model.slices = 1;
  model.slice_positions_m.clear();
  return model;
}

cfd_ancf::SpanwiseLoadInput load_input(
    double active_min, double active_max,
    const std::vector<double>& positions,
    const std::vector<std::array<double, 3>>& values) {
  if (positions.size() != values.size()) throw std::runtime_error("test sample size mismatch");
  cfd_ancf::SpanwiseLoadInput input;
  input.mode = cfd_ancf::SpanwiseLoadReconstruction::PiecewiseLinearDistributed;
  input.endpoint_policy = cfd_ancf::SpanwiseEndpointPolicy::NearestConstant;
  input.active_region = {active_min, active_max};
  for (std::size_t i = 0; i < positions.size(); ++i)
    input.samples.push_back({positions[i], values[i]});
  return input;
}

void print_vector(const std::vector<double>& values) {
  std::cout << '[';
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i != 0) std::cout << ',';
    std::cout << std::setprecision(17) << values[i];
  }
  std::cout << ']';
}

void emit_case(const std::string& name, const cfd_ancf::Model& model,
              const cfd_ancf::SpanwiseLoadInput& input) {
  const auto result = cfd_ancf::external_force(model, input);
  std::cout << "{\"name\":\"" << name << "\",\"length\":"
            << std::setprecision(17) << model.length_m << ",\"elements\":"
            << model.elements << ",\"q\":";
  print_vector(result);
  std::cout << "}\n";
}

void emit_legacy_case() {
  auto model = test_model(4, 10.0);
  model.slices = 3;
  model.slice_positions_m = {1.0, 4.0, 9.0};
  const std::vector<double> force = {2.0, 3.0, 0.0, 1.0, 0.0, 4.0, -1.0, 2.0, 0.5};
  const auto result = cfd_ancf::external_force(model, force);
  std::cout << "{\"name\":\"legacy_point_lumped\",\"length\":10,\"elements\":4,\"q\":";
  print_vector(result);
  std::cout << "}\n";
}

void emit_sine_case(int sample_count) {
  constexpr double length = 10.0;
  std::vector<double> positions;
  std::vector<std::array<double, 3>> values;
  for (int i = 0; i < sample_count; ++i) {
    const double s = length * static_cast<double>(i) / static_cast<double>(sample_count - 1);
    positions.push_back(s);
    values.push_back({std::sin(0.7 * s), 0.5 * std::cos(0.7 * s),
                      0.2 * std::sin(0.3 * s)});
  }
  emit_case("sine_ns_" + std::to_string(sample_count), test_model(11, length),
            load_input(0.0, length, positions, values));
}

}  // namespace

int main() {
  try {
    const auto constant = std::array<double, 3>{2.0, -1.0, 0.5};
    emit_case("constant", test_model(4, 10.0),
              load_input(1.0, 9.0, {1.7, 4.9, 8.2}, {constant, constant, constant}));

    emit_case("linear", test_model(7, 10.0),
              load_input(0.5, 9.5, {0.5, 4.0, 9.5},
                         {{1.0 + 0.2 * 0.5, -2.0 + 0.3 * 0.5, 0.5 - 0.1 * 0.5},
                          {1.0 + 0.2 * 4.0, -2.0 + 0.3 * 4.0, 0.5 - 0.1 * 4.0},
                          {1.0 + 0.2 * 9.5, -2.0 + 0.3 * 9.5, 0.5 - 0.1 * 9.5}}));

    emit_case("nonuniform_samples", test_model(11, 10.0),
              load_input(0.0, 10.0, {0.4, 1.7, 6.2, 9.6},
                         {{0.2, 1.0, -0.5}, {1.1, -0.4, 0.3},
                          {-0.7, 0.8, 1.2}, {0.4, 0.2, -0.1}}));

    emit_case("endpoint_extension", test_model(4, 10.0),
              load_input(0.3, 9.7, {1.2, 4.6, 8.4},
                         {{1.5, -0.2, 0.4}, {-0.5, 0.8, 0.1},
                          {0.9, 0.3, -0.6}}));

    emit_case("zero_outside", test_model(7, 10.0),
              load_input(2.0, 8.0, {3.0, 5.0, 7.0},
                         {{1.0, 0.0, 0.0}, {0.0, 2.0, 0.0},
                          {-1.0, 0.0, 0.5}}));

    emit_case("ne_4_ns_3", test_model(4, 10.0),
              load_input(0.5, 9.5, {1.1, 4.4, 8.8},
                         {{0.2, 1.0, 0.0}, {1.2, -0.5, 0.4}, {-0.3, 0.8, 1.1}}));
    emit_case("ne_7_ns_5", test_model(7, 10.0),
              load_input(0.5, 9.5, {0.7, 2.3, 4.1, 7.6, 9.2},
                         {{0.2, 1.0, 0.0}, {0.8, -0.2, 0.4}, {1.1, 0.5, 0.2},
                          {-0.4, 0.7, 0.9}, {0.3, 0.1, -0.6}}));
    emit_case("ne_11_ns_4", test_model(11, 10.0),
              load_input(0.5, 9.5, {1.1, 3.9, 6.4, 8.8},
                         {{0.2, 1.0, 0.0}, {1.2, -0.5, 0.4}, {-0.3, 0.8, 1.1},
                          {0.5, -0.1, 0.2}}));

    emit_legacy_case();
    emit_sine_case(5);
    emit_sine_case(10);
    emit_sine_case(20);
    emit_sine_case(40);
  } catch (const std::exception& error) {
    std::cerr << "SPANWISE_TEST_EXCEPTION=" << error.what() << '\n';
    return 1;
  }
  return 0;
}
