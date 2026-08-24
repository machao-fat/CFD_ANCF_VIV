function report = test_ancf_physics()
%TEST_ANCF_PHYSICS Unit and whole-structure checks for the ANCF refactor.
this_file = mfilename('fullpath');
project_root = fileparts(fileparts(fileparts(this_file)));
src = fullfile(project_root,'src','structure_ancf_matlab');
addpath(src);

model = vertical_ttr_case('L',2.0,'D',0.02,'dInner',0.015,'nElem',2, ...
    'nSlices',3,'topTension_N',0,'dt',2.0e-3);
ne = model.geometry.n_elem;
ndof = model.geometry.ndof;
qrigid = zeros(ndof,1);
t = [1;2;3]; t = t/norm(t);
r0 = [0.2;-0.4;0.1];
for inode = 0:ne
    base = 6*inode+1;
    qrigid(base:base+2) = r0 + inode*model.geometry.L/ne*t;
    qrigid(base+3:base+5) = t;
end
[Qrigid,~] = ancf_internal_force_tangent(qrigid,model);
rigid_force_error = norm(Qrigid,inf);
assert(rigid_force_error < 1e-5, 'Rigid translation/rotation does not preserve zero strain.');

stretch = 1.01;
qstretch = qrigid;
for inode = 0:ne
    base = 6*inode+1;
    qstretch(base:base+2) = r0 + stretch*inode*model.geometry.L/ne*t;
    qstretch(base+3:base+5) = stretch*t;
end
[Qstretch,~] = ancf_internal_force_tangent(qstretch,model);
eps_expected = 0.5*(stretch^2-1);
N_expected = model.material.EA*eps_expected*stretch;
top_pos_dofs = 6*(model.geometry.n_node-1)+1:6*(model.geometry.n_node-1)+3;
axial_force_error = abs(dot(Qstretch(top_pos_dofs),t) - N_expected)/max(1,abs(N_expected));
assert(axial_force_error < 1e-5, 'Uniform axial force does not match EA*epsilon.');

M = ancf_mass_matrix(model);
mass_symmetry_error = norm(M-M.','fro')/max(1,norm(M,'fro'));
mass_min_eigenvalue = min(eig((M+M.')/2));
assert(mass_symmetry_error < 1e-12 && mass_min_eigenvalue > 0, 'Mass matrix check failed.');

[fixed,free,~] = ancf_constraints(model);
[~,Kstatic] = ancf_internal_force_tangent(qrigid,model);
Kff = Kstatic(free,free); Mff = M(free,free);
lambda = eig(0.5*(Kff+Kff.'),0.5*(Mff+Mff.'));
lambda = real(lambda(lambda > 1e-8));
modal_frequency_Hz = sort(sqrt(lambda)/(2*pi));
assert(~isempty(modal_frequency_Hz) && all(isfinite(modal_frequency_Hz)), 'Modal check failed.');

model_low = vertical_ttr_case('L',10,'D',0.028,'dInner',0.024,'nElem',4, ...
    'nSlices',5,'topTension_N',100);
state_low = ancf_initialize(model_low);
assert(state_low.static.converged, 'Low-tension static initialization failed.');

report = struct('passed',true,'rigid_force_error',rigid_force_error, ...
    'axial_force_relative_error',axial_force_error, ...
    'mass_symmetry_error',mass_symmetry_error, ...
    'mass_min_eigenvalue',mass_min_eigenvalue, ...
    'first_modal_frequency_Hz',modal_frequency_Hz(1), ...
    'low_tension_static_iterations',state_low.static.iterations, ...
    'fixed_dof_count',numel(fixed),'free_dof_count',numel(free));
fprintf('PASS ANCF physics: rigid=%.3e axial=%.3e M_sym=%.3e f1=%.6g Hz lowT_iter=%d\n', ...
    report.rigid_force_error,report.axial_force_relative_error,report.mass_symmetry_error, ...
    report.first_modal_frequency_Hz,report.low_tension_static_iterations);
end
