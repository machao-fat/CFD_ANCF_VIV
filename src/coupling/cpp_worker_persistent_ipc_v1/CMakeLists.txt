cmake_minimum_required(VERSION 3.20)
project(cfd_ancf_cpp_worker LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(cfd_ancf_cpp_worker worker_main.cpp)
add_executable(cfd_ancf_ancf_kernel_selftest ancf_kernel.cpp ancf_kernel_selftest.cpp)
add_executable(cfd_ancf_dense_solver_selftest ancf_solver_selftest.cpp)
add_executable(cfd_ancf_ancf_kernel_worker ancf_kernel.cpp ancf_worker_main.cpp)
add_executable(cfd_ancf_ancf_kernel_diagnostic ancf_kernel.cpp ancf_kernel_diagnostic.cpp)
add_executable(cfd_ancf_ancf_kernel_worker_double_solve ancf_kernel.cpp ancf_worker_main.cpp)
add_executable(cfd_ancf_physics_ownership_selftest
  ancf_kernel.cpp
  ../cpp_physics_ownership_v1/physics_ownership.cpp
  ../cpp_physics_ownership_v1/physics_ownership_selftest.cpp)
add_executable(cfd_ancf_physics_ownership_worker
  ancf_kernel.cpp
  ../cpp_physics_ownership_v1/physics_ownership_worker_main.cpp
  ../cpp_physics_ownership_v1/physics_ownership.cpp)
add_executable(cfd_ancf_physics_ownership_worker_double_solve
  ancf_kernel.cpp
  ../cpp_physics_ownership_v1/physics_ownership_worker_main.cpp
  ../cpp_physics_ownership_v1/physics_ownership.cpp)
target_compile_definitions(cfd_ancf_physics_ownership_worker_double_solve PRIVATE CFD_ANCF_USE_DOUBLE_SOLVE=1)
if (WIN32)
  target_link_libraries(cfd_ancf_cpp_worker PRIVATE bcrypt)
  target_link_libraries(cfd_ancf_ancf_kernel_worker PRIVATE bcrypt)
  target_link_libraries(cfd_ancf_ancf_kernel_worker_double_solve PRIVATE bcrypt)
  target_link_libraries(cfd_ancf_physics_ownership_worker PRIVATE bcrypt)
  target_link_libraries(cfd_ancf_physics_ownership_worker_double_solve PRIVATE bcrypt)
  target_link_libraries(cfd_ancf_physics_ownership_selftest PRIVATE bcrypt)
endif()
if (MSVC)
  target_compile_options(cfd_ancf_cpp_worker PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_dense_solver_selftest PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_kernel_selftest PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_kernel_worker PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_kernel_diagnostic PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_kernel_worker_double_solve PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_physics_ownership_selftest PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_physics_ownership_worker PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_physics_ownership_worker_double_solve PRIVATE /W4 /permissive-)
  target_compile_definitions(cfd_ancf_ancf_kernel_worker_double_solve PRIVATE CFD_ANCF_USE_DOUBLE_SOLVE=1)
else()
  target_compile_options(cfd_ancf_cpp_worker cfd_ancf_dense_solver_selftest
                         cfd_ancf_ancf_kernel_selftest cfd_ancf_ancf_kernel_worker
                         cfd_ancf_ancf_kernel_diagnostic cfd_ancf_ancf_kernel_worker_double_solve
                         cfd_ancf_physics_ownership_selftest cfd_ancf_physics_ownership_worker
                         cfd_ancf_physics_ownership_worker_double_solve
                         PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()
