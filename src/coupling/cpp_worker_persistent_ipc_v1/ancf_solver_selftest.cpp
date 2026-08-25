// Solver-only regression executable. Including the implementation keeps the
// dense LU helper private to the worker while allowing a deterministic pivot
// lineage test without widening the production API.
#include "ancf_kernel.cpp"

#include <cmath>
#include <iostream>

int main() {
  cfd_ancf::Matrix matrix(3, 3);
  matrix(0, 0) = 0.0; matrix(0, 1) = 2.0; matrix(0, 2) = 1.0;
  matrix(1, 0) = 1.0; matrix(1, 1) = 1.0; matrix(1, 2) = 0.0;
  matrix(2, 0) = 2.0; matrix(2, 1) = 4.0; matrix(2, 2) = 3.0;
  const std::vector<double> rhs{7.0, 3.0, 19.0};
  const auto solution = cfd_ancf::solve(matrix, rhs);
  const std::vector<double> expected{1.0, 2.0, 3.0};
  if (solution.size() != expected.size()) return 2;
  for (std::size_t i = 0; i < expected.size(); ++i)
    if (!std::isfinite(solution[i]) || std::abs(solution[i] - expected[i]) > 1.0e-12) return 3;
  std::cout << "ancf_solver_selftest=pass second_pivot=1\n";
  return 0;
}
