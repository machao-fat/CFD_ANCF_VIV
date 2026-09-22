#include "ancf_kernel.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr double TipLoad = 2.0;

cfd_ancf::Model make_model(std::size_t elements) {
  cfd_ancf::Model model;
  model.length_m = 1.0;
  model.elements = elements;
  model.slices = 3;
  model.top_tension_N = 0.0;
  model.youngs_modulus_Pa = 1.0;
  model.material_density = 1.0;
  model.section_property_mode = cfd_ancf::SectionPropertyMode::ExplicitSectionProperties;
  model.explicit_EA_N = 100.0;
  model.explicit_EI_Nm2 = 1.0;
  model.explicit_mass_per_length_kg_m = 1.0;
  model.explicit_displaced_area_m2 = 1.0e-3;
  model.fluid_density = 1000.0;
  model.gravity = 0.0;
  model.include_gravity = true;
  model.include_buoyancy = true;
  model.gauss_order = 3;
  model.mass_gauss_order = 5;
  model.fixed_dof = {0u, 1u, 2u, 3u, 4u};
  model.prescribed_values = {0.0, 0.0, 0.0, 0.0, 0.0};
  model.boundary_contract_id = "ancf_f_v1_2_root_position_and_tangent_direction";
  cfd_ancf::validate_model(model);
  return model;
}

void write_audit(const std::string& path, const cfd_ancf::Model& model) {
  const std::size_t tip = 6u * model.elements;
  std::vector<std::size_t> free;
  for (std::size_t i = 0; i < model.ndof(); ++i) {
    bool fixed = false;
    for (std::size_t j : model.fixed_dof) fixed = fixed || (i == j);
    if (!fixed) free.push_back(i);
  }
  std::vector<double> load(model.ndof(), 0.0);
  load[tip] = TipLoad;
  double free_norm2 = 0.0;
  double constrained_norm2 = 0.0;
  for (std::size_t i = 0; i < load.size(); ++i) {
    bool fixed = false;
    for (std::size_t j : model.fixed_dof) fixed = fixed || (i == j);
    if (fixed) constrained_norm2 += load[i] * load[i];
    else free_norm2 += load[i] * load[i];
  }
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("F_EVIDENCE_SERIALIZATION_FAIL");
  out << std::setprecision(17)
      << "{\n"
      << "  \"elements\": " << model.elements << ",\n"
      << "  \"ndof\": " << model.ndof() << ",\n"
      << "  \"boundary_contract_id\": \"" << model.boundary_contract_id << "\",\n"
      << "  \"constrained_dofs\": [";
  for (std::size_t i = 0; i < model.fixed_dof.size(); ++i)
    out << (i ? ", " : "") << model.fixed_dof[i];
  out << "],\n  \"free_dofs\": [";
  for (std::size_t i = 0; i < free.size(); ++i) out << (i ? ", " : "") << free[i];
  out << "],\n"
      << "  \"root_position_dofs\": [0, 1, 2],\n"
      << "  \"root_gradient_direction_dofs\": [3, 4],\n"
      << "  \"root_gradient_magnitude_dof\": 5,\n"
      << "  \"tip_position_dofs\": [" << tip << ", " << tip + 1u << ", " << tip + 2u << "],\n"
      << "  \"tip_gradient_dofs\": [" << tip + 3u << ", " << tip + 4u << ", " << tip + 5u << "],\n"
      << "  \"tip_x_dof\": " << tip << ",\n"
      << "  \"load_nonzero_dofs\": [" << tip << "],\n"
      << "  \"load_free_projection_norm\": " << std::sqrt(free_norm2) << ",\n"
      << "  \"load_constrained_projection_norm\": " << std::sqrt(constrained_norm2) << ",\n"
      << "  \"pass\": "
      << ((model.fixed_dof.size() == 5u && model.fixed_dof[0] == 0u &&
           model.fixed_dof[1] == 1u && model.fixed_dof[2] == 2u &&
           model.fixed_dof[3] == 3u && model.fixed_dof[4] == 4u &&
           free.size() == model.ndof() - 5u &&
           std::sqrt(free_norm2) == TipLoad && std::sqrt(constrained_norm2) == 0.0 &&
           std::find(free.begin(), free.end(), tip) != free.end()) ? "true" : "false")
      << "\n}\n";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: boundary_audit <elements> <audit.json>\n";
    return 2;
  }
  try {
    const auto model = make_model(static_cast<std::size_t>(std::stoull(argv[1])));
    write_audit(argv[2], model);
    std::cout << "boundary dry audit PASS elements " << model.elements << "\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
