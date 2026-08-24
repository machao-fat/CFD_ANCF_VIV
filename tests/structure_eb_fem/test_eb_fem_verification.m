function report = test_eb_fem_verification()
%TEST_EB_FEM_VERIFICATION Independent verification of the EB comparator.
% The tests use only the equations implemented in the new branch and
% standard simply-supported Euler-Bernoulli reference solutions.

this_file = mfilename('fullpath');
project_root = fileparts(fileparts(fileparts(this_file)));
src_eb = fullfile(project_root,'src','structure_eb_fem_matlab');
src_ancf = fullfile(project_root,'src','structure_ancf_matlab');
addpath(src_eb);
addpath(src_ancf);

results_dir = fullfile(project_root,'results','04_eb_fem_verification');
if ~exist(results_dir,'dir'), mkdir(results_dir); end

report = struct();
report.schema_version = '0.1.0';
report.passed = false;
report.kinematics = 'linear_Euler_Bernoulli_small_displacement_small_rotation';
report.boundary = 'u=v=0 at both ends; theta_u/theta_v free';

report.uniform_load = verify_uniform_load(src_eb);
report.point_load = verify_point_load(src_eb);
report.modal = verify_modal_frequency(src_eb);
report.pretension_profiles = verify_pretension_profiles(src_eb);
report.time_integration = verify_newmark_and_energy(src_eb);
report.virtual_work = verify_shared_mapping(src_eb,src_ancf);
report.small_deformation_ancf_comparison = verify_small_deformation_consistency(src_eb,src_ancf);
report.passed = true;

json_text = jsonencode(report);
fid = fopen(fullfile(results_dir,'eb_fem_verification_summary.json'),'w');
assert(fid > 0,'Could not open EB verification summary for writing.');
cleanup = onCleanup(@() fclose(fid));
fwrite(fid,json_text,'char');
clear cleanup;

fprintf(['PASS EB verification: uniform=%.3e point=%.3e modal=%.3e ', ...
    'dt=%.3e energy=%.3e map=%.3e smallLoad=%.3e\n'], ...
    report.uniform_load.max_relative_error,report.point_load.finest_relative_error, ...
    report.modal.relative_frequency_error,report.time_integration.time_step_difference_inf, ...
    report.time_integration.energy_relative_drift,report.virtual_work.eb_relative_error, ...
    report.small_deformation_ancf_comparison.max_displacement_difference_m);
end

function model = zero_tension_case(src,nElem,nSlices)
addpath(src);
model = eb_ttr_case('L',2.0,'D',0.020,'dInner',0.015, ...
    'nElem',nElem,'nSlices',nSlices,'topTension_N',0.0, ...
    'pretension_mode','paper_formula','paper_unit_weight_Npm',0.0, ...
    'dt',1.0e-3);
model.physics.include_gravity = false;
model.physics.include_buoyancy = false;
model.static.distributed_load_Npm = [0;0];
model.static.external_slice_force_N = zeros(nSlices,3);
end

function result = verify_uniform_load(src)
model = zero_tension_case(src,4,9);
qline = 1.0;
model.static.distributed_load_Npm = [0;qline];
state = eb_initialize(model);
s = state.output.s_ref_m;
L = model.geometry.L; EI = model.material.EI;
reference = qline*s.*(L^3-2*L*s.^2+s.^3)/(24*EI);
err = max(abs(state.output.y_m-reference));
scale = max(1e-15,max(abs(reference)));
nodal_s = (0:model.geometry.n_elem).'*model.geometry.L/model.geometry.n_elem;
nodal_reference = qline*nodal_s.*(L^3-2*L*nodal_s.^2+nodal_s.^3)/(24*EI);
nodal_values = state.q(3:4:end);
nodal_err = max(abs(nodal_values-nodal_reference));
result = struct('max_absolute_error_m',err,'max_relative_error',err/scale, ...
    'max_nodal_absolute_error_m',nodal_err, ...
    'static_free_residual_inf_N',state.static.residual,'reference_max_m',max(reference));
assert(result.max_relative_error < 2e-3,'Uniform-load analytical solution mismatch.');
assert(nodal_err < 1e-10,'Uniform-load nodal values do not match the analytical solution.');
assert(state.static.residual < 1e-9,'Uniform-load constrained residual is not small.');
end

function result = verify_point_load(src)
ne_list = [2,4,8,16];
errors = zeros(size(ne_list));
P = 1.0; L = 2.0; a = 0.37*L; b = L-a;
for k = 1:numel(ne_list)
    model = zero_tension_case(src,ne_list(k),21);
    state = eb_initialize(model);
    Q = eb_point_load(state.model,a,[0;P]);
    [fixed,free,values] = eb_constraints(state.model);
    q = zeros(model.geometry.ndof,1); q(fixed) = values(fixed);
    q(free) = state.model.matrices.K(free,free)\Q(free);
    state.q = q; state.qd(:) = 0; state.qdd(:) = 0;
    state.output = eb_postprocess(state);
    s = state.output.s_ref_m;
    reference = zeros(size(s));
    left = s <= a;
    reference(left) = P*b*s(left).*(L^2-b^2-s(left).^2)/(6*L*model.material.EI);
    xr = L-s(~left);
    reference(~left) = P*a*xr.*(L^2-a^2-xr.^2)/(6*L*model.material.EI);
    errors(k) = max(abs(state.output.y_m-reference))/max(1e-15,max(abs(reference)));
end
assert(errors(end) < 1e-5,'Point-load mesh refinement did not reach the reference solution: %s.',mat2str(errors,6));
result = struct('nElem',ne_list,'max_relative_error',errors,'finest_relative_error',errors(end), ...
    'load_N',P,'load_s_m',a);
end

function result = verify_modal_frequency(src)
model = zero_tension_case(src,16,17);
model.pretension.mode = 'paper_formula';
model.pretension.paper_unit_weight_Npm = 0.0;
model.pretension.top_tension_N = 500.0;
state = eb_initialize(model);
modal = eb_modal_analysis(state.model,3);
k = pi/model.geometry.L;
lambda_ref = (model.material.EI*k^4+model.pretension.top_tension_N*k^2)/ ...
    model.material.mass_per_length;
f_ref = sqrt(lambda_ref)/(2*pi);
err = abs(modal.frequency_Hz(1)-f_ref)/f_ref;
assert(err < 5e-3,'Prestressed first frequency mismatch.');
result = struct('finite_element_frequency_Hz',modal.frequency_Hz(:).', ...
    'reference_first_frequency_Hz',f_ref,'relative_frequency_error',err, ...
    'mass_per_length_kgpm',model.material.mass_per_length, ...
    'top_tension_N',model.pretension.top_tension_N);
end

function result = verify_pretension_profiles(src)
model_a = eb_ttr_case('L',10,'nElem',4,'nSlices',5,'topTension_N',2000, ...
    'pretension_mode','ancf_initial_balance');
expected_bottom = model_a.pretension.top_tension_N - ...
    model_a.pretension.ancf_initial_weight_Npm*model_a.geometry.L;
assert(abs(eb_pretension_profile(model_a,0)-expected_bottom) < 1e-12);
assert(abs(eb_pretension_profile(model_a,model_a.geometry.L)-2000) < 1e-12);

model_p = eb_ttr_case('L',10,'nElem',4,'nSlices',5,'topTension_N',2000, ...
    'pretension_mode','paper_formula','paper_unit_weight_Npm',321.0);
expected_paper = 2000-321*5;
assert(abs(eb_pretension_profile(model_p,5)-expected_paper) < 1e-12);
result = struct('ancf_initial_balance_bottom_N',eb_pretension_profile(model_a,0), ...
    'ancf_initial_balance_top_N',eb_pretension_profile(model_a,10), ...
    'paper_formula_mid_N',eb_pretension_profile(model_p,5));
end

function result = verify_newmark_and_energy(src)
model = zero_tension_case(src,8,9);
state_coarse = make_first_mode_state(model,2.0e-3,1.0e-3);
state_fine = make_first_mode_state(model,1.0e-3,1.0e-3);
energy_initial = state_coarse.initial_energy_J;
for k = 1:50, state_coarse = eb_advance_step(state_coarse,[],2.0e-3); end
for k = 1:100, state_fine = eb_advance_step(state_fine,[],1.0e-3); end
qdiff = norm(state_coarse.q-state_fine.q,inf);
energyf = state_coarse.output.mechanical_energy_J;
energy_drift = abs(energyf-energy_initial)/max(1e-30,abs(energy_initial));
assert(qdiff < 5e-5,'Newmark time-step refinement is too large: %.3e.',qdiff);
assert(energy_drift < 2e-9,'Undamped free-vibration energy drift is too large: %.3e.',energy_drift);
result = struct('time_step_difference_inf',qdiff,'energy_relative_drift',energy_drift, ...
    'initial_energy_J',energy_initial,'final_energy_J',energyf,'beta',0.25,'gamma',0.5);
end

function state = make_first_mode_state(model,dt,amplitude)
model.time.dt = dt;
state = eb_initialize(model);
L = model.geometry.L; Le = L/model.geometry.n_elem;
q = zeros(model.geometry.ndof,1);
for inode = 1:model.geometry.n_node
    s = (inode-1)*Le;
    value = amplitude*sin(pi*s/L);
    slope = amplitude*pi/L*cos(pi*s/L);
    base = 4*(inode-1)+1;
    q(base+2) = value;
    q(base+3) = slope;
end
[fixed,free,~] = eb_constraints(model);
q(fixed) = 0;
qdd = zeros(size(q));
qdd(free) = -state.model.matrices.M(free,free)\(state.model.matrices.K(free,:)*q);
state.q = q; state.qd(:) = 0; state.qdd = qdd;
state.output = eb_postprocess(state);
state.initial_energy_J = state.output.mechanical_energy_J;
end

function result = verify_shared_mapping(src_eb,src_ancf)
% Check discrete virtual work with one force vector per slice.
model = eb_ttr_case('L',5,'D',0.02,'dInner',0.015,'nElem',4,'nSlices',5);
model.mapping = eb_build_mapping(model);
dq = (1:model.geometry.ndof).'/17;
slice_force = [1:5;11:15;21:25].';
slice_force_eb = slice_force; slice_force_eb(:,3) = 0;
Fxy = zeros(2*5,1); Fxy(1:2:end)=slice_force_eb(:,1); Fxy(2:2:end)=slice_force_eb(:,2);
lhs_eb = (model.mapping.H*dq).'*Fxy;
rhs_eb = dq.'*eb_external_load(model,slice_force_eb);

ancf_model = vertical_ttr_case('L',5,'D',0.02,'dInner',0.015,'nElem',4,'nSlices',5);
ancf_model.mapping = ancf_build_mapping(ancf_model);
dq3 = (1:ancf_model.geometry.ndof).'/19;
F3 = zeros(3*5,1); F3(1:3:end)=slice_force(:,1); F3(2:3:end)=slice_force(:,2); F3(3:3:end)=slice_force(:,3);
lhs_ancf = (ancf_model.mapping.H3*dq3).'*F3;
rhs_ancf = dq3.'*ancf_external_load(ancf_model,slice_force);
eb_err = abs(lhs_eb-rhs_eb)/max(1,abs(lhs_eb));
ancf_err = abs(lhs_ancf-rhs_ancf)/max(1,abs(lhs_ancf));
assert(eb_err < 1e-13 && ancf_err < 1e-13, ...
    'Shared H/H^T virtual work failed: EB %.3e ANCF %.3e.',eb_err,ancf_err);
result = struct('eb_relative_error',eb_err,'ancf_relative_error',ancf_err, ...
    'eb_virtual_work',lhs_eb,'ancf_virtual_work',lhs_ancf);
end

function result = verify_small_deformation_consistency(src_eb,src_ancf)
L = 2.0; nElem = 8; nSlices = 21; qline = 1.0e-3; topTension = 500.0;
ancf = vertical_ttr_case('L',L,'D',0.020,'dInner',0.015,'nElem',nElem, ...
    'nSlices',nSlices,'topTension_N',topTension,'dt',1.0e-3);
ancf.physics.include_gravity = false; ancf.physics.include_buoyancy = false;
ancf.mapping = ancf_build_mapping(ancf);
slice_force = zeros(nSlices,3); slice_force(:,2) = qline*ancf.mapping.slice_weights_m;
ancf.static.external_slice_force_N = slice_force;
state_a = ancf_initialize(ancf);

eb = eb_ttr_case('L',L,'D',0.020,'dInner',0.015,'nElem',nElem, ...
    'nSlices',nSlices,'topTension_N',topTension,'dt',1.0e-3, ...
    'pretension_mode','paper_formula','paper_unit_weight_Npm',0.0);
eb.physics.include_gravity = false; eb.physics.include_buoyancy = false;
eb.static.external_slice_force_N = slice_force;
state_e = eb_initialize(eb);

diff_y = max(abs(state_a.output.y_m-state_e.output.y_m));
scale_y = max(1e-15,max(abs(state_e.output.y_m)));
% Quantify modal agreement by comparing the nearest transverse ANCF mode.
modal_e = eb_modal_analysis(state_e.model,3);
[fixed,free,~] = ancf_constraints(state_a.model);
[V,D] = eig(0.5*(ancf_tangent_at_state(state_a,free)+ancf_tangent_at_state(state_a,free).'), ...
    0.5*(state_a.model.mass_matrix(free,free)+state_a.model.mass_matrix(free,free).'));
freq_a = sqrt(real(diag(D)))/(2*pi);
freq_a = sort(freq_a(isfinite(freq_a) & freq_a > 1e-8));
freq_diff = min(abs(freq_a-modal_e.frequency_Hz(1)))/modal_e.frequency_Hz(1);
assert(diff_y/scale_y < 2e-2,'Small-load ANCF/EB displacement mismatch exceeds 2 percent.');
result = struct('max_displacement_difference_m',diff_y, ...
    'relative_displacement_difference',diff_y/scale_y, ...
    'eb_first_frequency_Hz',modal_e.frequency_Hz(1), ...
    'nearest_ancf_frequency_difference',freq_diff, ...
    'ancf_static_iterations',state_a.static.iterations, ...
    'ancf_min_tension_N',min(state_a.output.tension_N));
end

function Kff = ancf_tangent_at_state(state,free)
[~,K] = ancf_internal_force_tangent(state.q,state.model);
Kff = K(free,free);
end
