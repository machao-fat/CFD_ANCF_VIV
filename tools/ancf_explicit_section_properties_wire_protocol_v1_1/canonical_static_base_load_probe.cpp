#include "ancf_kernel.hpp"

#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  if (argc != 2 && argc != 6) return 2;
  cfd_ancf::Model model;
  model.length_m = 1.0;
  model.diameter_m = 0.028;
  model.inner_diameter_m = 0.024;
  model.elements = 1;
  model.slices = 1;
  model.top_tension_N = 0.0;
  model.youngs_modulus_Pa = 2.07e11;
  model.material_density = 7850.0;
  model.fluid_density = 1025.0;
  model.gravity = 9.81;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  model.max_newton = 40;
  model.dt_s = 0.001;
  model.fixed_dof = {0u, 1u, 2u, 6u, 7u};
  model.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0};
  model.boundary_contract_id = "ancf_v1_wire_static_initializer";
  if (std::string(argv[1]) == "explicit") {
    if (argc != 6) return 3;
    model.section_property_mode = cfd_ancf::SectionPropertyMode::ExplicitSectionProperties;
    model.explicit_EA_N = std::stod(argv[2]);
    model.explicit_EI_Nm2 = std::stod(argv[3]);
    model.explicit_mass_per_length_kg_m = std::stod(argv[4]);
    model.explicit_displaced_area_m2 = std::stod(argv[5]);
  } else if (std::string(argv[1]) != "legacy" || argc != 2) {
    return 4;
  }
  try {
    const auto load = cfd_ancf::static_base_load(model);
    std::cout << std::setprecision(17);
    for (std::size_t index = 0; index < load.size(); ++index) {
      if (index != 0) std::cout << ' ';
      std::cout << load[index];
    }
    std::cout << '\n';
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 5;
  }
  return 0;
}
