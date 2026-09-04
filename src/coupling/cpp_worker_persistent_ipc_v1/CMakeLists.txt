cmake_minimum_required(VERSION 3.20)
project(cfd_ancf_cpp_worker LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if (MSVC)
  # MATLAB golden traces require non-contracted IEEE double operations.  /O2
  # alone permits FMA contraction, which changes the Newmark predictor by one
  # ulp and is amplified by the ANCF tangent.
  add_compile_options(/fp:strict)
  # Apply exception unwinding semantics to every target, including targets
  # declared below.  Placing this directory option after add_executable()
  # leaves existing targets without /EHsc under Visual Studio.
  add_compile_options(/EHsc)
endif()
add_executable(cfd_ancf_cpp_worker worker_main.cpp)
add_executable(cfd_ancf_ancf_kernel_selftest ancf_kernel.cpp ancf_kernel_selftest.cpp)
add_executable(cfd_ancf_dense_solver_selftest ancf_solver_selftest.cpp)
add_executable(cfd_ancf_ancf_kernel_worker ancf_kernel.cpp ancf_worker_main.cpp)
add_executable(cfd_ancf_cpp_state_initializer ancf_kernel.cpp ancf_state_initializer.cpp)
add_executable(cfd_ancf_ancf_kernel_diagnostic ancf_kernel.cpp ancf_kernel_diagnostic.cpp)
add_executable(cfd_ancf_ancf_forensic_diagnostic ancf_kernel.cpp ancf_forensic_diagnostic.cpp)
add_executable(cfd_ancf_ancf_newton_trace_diagnostic ancf_kernel.cpp ancf_newton_trace_diagnostic.cpp)
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
  target_compile_options(cfd_ancf_cpp_state_initializer PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_kernel_diagnostic PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_forensic_diagnostic PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_newton_trace_diagnostic PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_ancf_kernel_worker_double_solve PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_physics_ownership_selftest PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_physics_ownership_worker PRIVATE /W4 /permissive-)
  target_compile_options(cfd_ancf_physics_ownership_worker_double_solve PRIVATE /W4 /permissive-)
  target_compile_definitions(cfd_ancf_ancf_kernel_worker_double_solve PRIVATE CFD_ANCF_USE_DOUBLE_SOLVE=1)
else()
  set(CFD_ANCF_WARNING_TARGETS
      cfd_ancf_cpp_worker
      cfd_ancf_dense_solver_selftest
      cfd_ancf_ancf_kernel_selftest
      cfd_ancf_ancf_kernel_worker
      cfd_ancf_cpp_state_initializer
      cfd_ancf_ancf_kernel_diagnostic
      cfd_ancf_ancf_kernel_worker_double_solve
      cfd_ancf_ancf_forensic_diagnostic
      cfd_ancf_ancf_newton_trace_diagnostic
      cfd_ancf_physics_ownership_selftest
      cfd_ancf_physics_ownership_worker
      cfd_ancf_physics_ownership_worker_double_solve)
  foreach(CFD_ANCF_WARNING_TARGET IN LISTS CFD_ANCF_WARNING_TARGETS)
    target_compile_options(${CFD_ANCF_WARNING_TARGET}
                           PRIVATE -Wall -Wextra -Wpedantic -Werror)
  endforeach()
endif()
