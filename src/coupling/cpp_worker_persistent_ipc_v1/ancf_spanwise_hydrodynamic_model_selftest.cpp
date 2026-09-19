#include "ancf_kernel.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

cfd_ancf::Model model() {
  cfd_ancf::Model value;
  value.length_m = 8.0;
  value.elements = 4;
  value.slices = 3;
  value.top_tension_N = 0.0;
  value.include_gravity = true;
  value.include_buoyancy = true;
  return value;
}

bool exactly_equal(const cfd_ancf::Matrix& left, const cfd_ancf::Matrix& right) {
  return left.rows == right.rows && left.cols == right.cols && left.data == right.data;
}

bool zero(const cfd_ancf::Matrix& value) {
  for (double entry : value.data) if (entry != 0.0) return false;
  return true;
}

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

}  // namespace

int main() {
  try {
    const cfd_ancf::Model legacy = model();
    cfd_ancf::Model shm1 = legacy;
    shm1.hydrodynamic_regions = {
        {0.0, 2.0, {1.0, 2.0, 0.0}, {3.0, 4.0, 0.0}},
        {2.0, 8.0, {5.0, 6.0, 0.0}, {7.0, 8.0, 0.0}},
    };
    cfd_ancf::validate_model(shm1);
    const cfd_ancf::State structural = cfd_ancf::make_reference_state(legacy);
    const cfd_ancf::State nonconnected = cfd_ancf::make_reference_state(shm1);
    require(exactly_equal(structural.mass, nonconnected.mass),
            "SHM1 unexpectedly changed State.mass before M3");
    require(exactly_equal(structural.damping, nonconnected.damping) && zero(nonconnected.damping),
            "SHM1 unexpectedly changed State.damping before M3");
    cfd_ancf::Model rayleigh_legacy = legacy;
    cfd_ancf::Model rayleigh_shm1 = shm1;
    rayleigh_legacy.damping_alpha = 0.125;
    rayleigh_shm1.damping_alpha = 0.125;
    const cfd_ancf::Matrix legacy_rayleigh = cfd_ancf::resolve_rayleigh_damping(
        rayleigh_legacy, structural.mass, structural.q, false);
    const cfd_ancf::Matrix shm1_rayleigh = cfd_ancf::resolve_rayleigh_damping(
        rayleigh_shm1, nonconnected.mass, nonconnected.q, false);
    require(exactly_equal(legacy_rayleigh, shm1_rayleigh),
            "SHM1 unexpectedly changed Rayleigh damping before M3");
    std::cout << "{\"status\":\"pass\",\"state_mass_nonconnection\":true,"
                 "\"state_damping_nonconnection\":true,\"rayleigh_nonconnection\":true,"
                 "\"touching_regions_accepted\":true}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "M2 model selftest failure: " << error.what() << '\n';
    return 1;
  }
}
