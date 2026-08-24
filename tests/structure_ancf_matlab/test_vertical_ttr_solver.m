function results = test_vertical_ttr_solver()
%TEST_VERTICAL_TTR_SOLVER Minimal regression tests for the new structure MVP.
this_file = mfilename('fullpath');
project_root = fileparts(fileparts(fileparts(this_file)));
src = fullfile(project_root,'src','structure_ancf_matlab');
addpath(src);

model = vertical_ttr_case('L',20,'D',0.028,'dInner',0.024,'nElem',4,'nSlices',5, ...
    'topTension_N',1000,'dt',1.0e-3);
state = ancf_initialize(model);
assert(state.static.converged, 'Static initialization did not converge.');
assert(all(isfinite(state.q)), 'Initial q contains non-finite values.');

qtest = state.q;
qtest(8) = qtest(8) + 0.05;
[~,Ktest] = ancf_internal_force_tangent(qtest,state.model);
vtest = randn(model.geometry.ndof,1);
vtest = vtest/norm(vtest);
hfd = 1.0e-6;
[Qp,~] = ancf_internal_force_tangent(qtest+hfd*vtest,state.model);
[Qm,~] = ancf_internal_force_tangent(qtest-hfd*vtest,state.model);
tangent_error = norm((Qp-Qm)/(2*hfd)-Ktest*vtest)/max(1,norm((Qp-Qm)/(2*hfd)));
assert(tangent_error < 1e-5, 'Analytic tangent finite-difference check failed.');

motion0 = ancf_slice_motion(state);
assert(abs(motion0.z_m(1)-model.boundary.bottom_position(3)) < 1e-10);
assert(all(size(motion0.x_m) == [numel(model.coupling.s_ref_m),1]));

Fslice = zeros(numel(model.coupling.s_ref_m),3);
Fslice(:,2) = 0.1;
Qslice = ancf_external_load(state,Fslice);
dq = randn(model.geometry.ndof,1);
lhs = (state.model.mapping.H3*dq).'*reshape(Fslice.',[],1);
rhs = dq.'*Qslice;
assert(abs(lhs-rhs) < 1e-10*max(1,abs(lhs)), 'Virtual-work transpose test failed.');

omega = [0.1;-0.2;0.3];
dqrot = zeros(model.geometry.ndof,1);
for inode = 0:model.geometry.n_elem
    base = 6*inode+1;
    rnode = state.q(base:base+2);
    snode = state.q(base+3:base+5);
    dqrot(base:base+2) = cross(omega,rnode);
    dqrot(base+3:base+5) = cross(omega,snode);
end
Frand = randn(numel(model.coupling.s_ref_m),3);
ancf_external_load(state,Frand);
slice_xyz = reshape(state.model.mapping.H3*state.q,3,[]).';
explicit_moment = sum(cross(slice_xyz,Frand,2),1).';
rotation_work = (state.model.mapping.H3*dqrot).'*reshape(Frand.',[],1);
moment_work = omega.'*explicit_moment;
moment_error = abs(rotation_work-moment_work);
assert(moment_error < 1e-10*max(1,abs(moment_work)), 'Resultant moment test failed.');

state = ancf_advance_step(state,Fslice);
assert(state.diagnostics.converged, 'Dynamic step did not converge.');
assert(state.step == 1 && state.t > 0, 'Time state was not advanced.');
assert(all(isfinite(state.output.curvature_mag_1pm)), 'Post-processing failed.');

% A restarted next step must match the continuous run.
checkpoint_file = fullfile(tempdir,'ancf_checkpoint_roundtrip.mat');
ancf_save_checkpoint(state,checkpoint_file);
state_cont = ancf_advance_step(state,Fslice);
state_restart = ancf_load_checkpoint(checkpoint_file);
state_restart = ancf_advance_step(state_restart,Fslice);
restart_error = norm(state_cont.q-state_restart.q,inf);
assert(restart_error < 1e-11, 'Checkpoint/restart state mismatch.');

tmp_file = fullfile(tempdir,'ancf_slice_loads_roundtrip.csv');
motion_file = fullfile(tempdir,'ancf_slice_motion_roundtrip.csv');
motion = ancf_slice_motion(state);
ancf_write_slice_motion_csv(motion,motion_file);
Tmotion = readtable(motion_file,'TextType','string');
assert(height(Tmotion) == numel(model.coupling.s_ref_m), 'Motion CSV row count failed.');
Fround = randn(numel(model.coupling.s_ref_m),3);
Tload = table(repmat(string(state.schema_version),size(Fround,1),1), ...
    repmat(state.step,size(Fround,1),1),zeros(size(Fround,1),1), ...
    repmat(state.t,size(Fround,1),1),model.coupling.s_ref_m(:),Fround(:,1),Fround(:,2),Fround(:,3), ...
    'VariableNames',{'schema_version','step','coupling_iteration','time_s','s_ref_m', ...
    'force_x_N','force_y_N','force_z_N'});
writetable(Tload,tmp_file);
[Fread,meta] = ancf_read_slice_loads_csv(tmp_file,state.model);
assert(norm(Fread-Fround,inf) < 1e-12 && meta.step == state.step, 'Load CSV roundtrip failed.');

results = struct('passed',true,'ndof',model.geometry.ndof,'nSlices',numel(model.coupling.s_ref_m), ...
    'static_iterations',state.static.iterations,'dynamic_iterations',state.diagnostics.iterations, ...
    'virtual_work_error',abs(lhs-rhs),'moment_work_error',moment_error, ...
    'tangent_error',tangent_error,'motion_rows',height(Tmotion), ...
    'load_roundtrip_error',norm(Fread-Fround,inf),'restart_error',restart_error,'time_s',state.t);
fprintf('PASS vertical TTR ANCF MVP: ndof=%d, slices=%d, t=%.6g s\n', ...
    results.ndof,results.nSlices,results.time_s);
end
