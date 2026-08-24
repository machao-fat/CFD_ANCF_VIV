function report = test_ancf_convergence()
%TEST_ANCF_CONVERGENCE Static mesh and time-step sanity checks.
this_file = mfilename('fullpath');
project_root = fileparts(fileparts(fileparts(this_file)));
src = fullfile(project_root,'src','structure_ancf_matlab');
addpath(src);

ne_list = [2,4,8];
max_y = zeros(size(ne_list));
static_iterations = zeros(size(ne_list));
for k = 1:numel(ne_list)
    model = vertical_ttr_case('L',10,'D',0.028,'dInner',0.024, ...
        'nElem',ne_list(k),'nSlices',21,'topTension_N',500);
    model.coupling.force_representation = 'line_Npm';
    model.static.external_slice_force_N(:,2) = 0.5;
    state = ancf_initialize(model);
    max_y(k) = max(abs(state.output.y_m));
    static_iterations(k) = state.static.iterations;
    assert(all(isfinite(state.q)), 'Mesh %d produced non-finite state.',ne_list(k));
end

mesh_change_2_to_4 = abs(max_y(2)-max_y(1));
mesh_change_4_to_8 = abs(max_y(3)-max_y(2));
assert(mesh_change_4_to_8 <= 1.25*mesh_change_2_to_4, ...
    'Mesh refinement did not reduce or stabilize the tip response.');

state_dt2 = run_perturbed_response(src,2.0e-3,5);
state_dt1 = run_perturbed_response(src,1.0e-3,10);
time_step_difference = norm(state_dt2.q-state_dt1.q,inf);
assert(time_step_difference < 5e-3, 'Time-step refinement changed the response excessively.');

report = struct('passed',true,'nElem',ne_list,'max_abs_y_m',max_y, ...
    'mesh_change_2_to_4_m',mesh_change_2_to_4, ...
    'mesh_change_4_to_8_m',mesh_change_4_to_8, ...
    'static_iterations',static_iterations,'time_step_difference_inf',time_step_difference);
fprintf('PASS ANCF convergence: maxY=[%.6g %.6g %.6g] d24=%.3e d48=%.3e dtDiff=%.3e\n', ...
    max_y(1),max_y(2),max_y(3),mesh_change_2_to_4,mesh_change_4_to_8,time_step_difference);
end

function state = run_perturbed_response(src,dt,nstep)
addpath(src);
model = vertical_ttr_case('L',10,'D',0.028,'dInner',0.024,'nElem',2, ...
    'nSlices',5,'topTension_N',500,'dt',dt);
state = ancf_initialize(model);
state.q(8) = state.q(8) + 0.01;
state.qdd(:) = 0;
for k = 1:nstep
    state = ancf_advance_step(state,zeros(5,3),dt);
end
end
