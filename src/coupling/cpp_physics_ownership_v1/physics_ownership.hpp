#pragma once

#include "../cpp_worker_persistent_ipc_v1/ancf_kernel.hpp"

#include <cstddef>
#include <string>
#include <vector>

namespace cfd_ancf::physics_ownership {

enum class ForceRepresentation { integrated_N, line_Npm };

struct BaseLoadBreakdown {
  std::vector<double> body_gravity;
  std::vector<double> body_buoyancy;
  std::vector<double> top_tension;
  std::vector<double> base;
};

struct CfdLoadBreakdown {
  ForceRepresentation representation = ForceRepresentation::integrated_N;
  std::vector<double> integrated_slice_force;
  std::vector<double> generalized_force;
};

void validate_model(const Model& model);
Matrix assemble_mass_matrix(const Model& model);
BaseLoadBreakdown assemble_base_load(const Model& model);
CfdLoadBreakdown assemble_cfd_load(const Model& model,
                                   const std::vector<double>& slice_force,
                                   ForceRepresentation representation,
                                   const std::vector<double>& slice_weights_m = {});
std::vector<double> add_loads(const std::vector<double>& lhs,
                              const std::vector<double>& rhs);
bool finite(const std::vector<double>& values);
double max_abs(const std::vector<double>& values);
std::string sha256_vector(const std::vector<double>& values);
const char* representation_name(ForceRepresentation representation);

}  // namespace cfd_ancf::physics_ownership
