function export_matlab_dual_run_40(source_mat, output_jsonl, global_start, bridge_start, count)
%EXPORT_MATLAB_DUAL_RUN_40 Export a bounded read-only MATLAB golden sequence.
loaded = load(char(source_mat), 'state');
state = loaded.state;
if nargin < 3, global_start = double(state.step) + 1; end
if nargin < 4, bridge_start = 1; end
if nargin < 5, count = 40; end
if count < 1 || count > 40, error('cppDual:Bound', 'count must be 1..40'); end
project_root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(genpath(fullfile(project_root, 'src', 'structure_ancf_matlab')));
slice_force = state.last_slice_force_N;
dt = state.model.time.dt;
tmp = [char(output_jsonl) '.tmp'];
fid = fopen(tmp, 'w', 'n', 'UTF-8');
if fid < 0, error('cppDual:Output', 'cannot open output'); end
cleanup = onCleanup(@() fclose(fid));
for index = 1:count
    global_step = double(global_start + index - 1);
    bridge_step = double(bridge_start + index - 1);
    target_time = double(state.t + dt);
    target_tick = round(target_time * 1e9);
    q_n = state.q(:); qd_n = state.qd(:); qdd_n = state.qdd(:);
    q_pred = q_n + dt*qd_n + dt^2*(0.5-state.model.time.beta)*qdd_n;
    Qext = state.base_load + ancf_external_load(state, slice_force);
    state = ancf_advance_step(state, slice_force, dt);
    [internal_after, ~] = ancf_internal_force_tangent(state.q, state.model);
    record = struct();
    record.run_id = 'matlab_dual_40'; record.case_id = 'matlab_dual_40_case';
    record.global_step = global_step; record.case_local_bridge_step = bridge_step;
    record.time_s = target_time; record.integer_tick = target_tick;
    record.q = state.q(:).'; record.qdot = state.qd(:).'; record.qddot = state.qdd(:).';
    record.internal_force = internal_after(:).'; record.external_force = Qext(:).';
    record.generalized_force = Qext(:).'; record.predictor = q_pred(:).';
    record.corrector = state.q(:).'; record.residual = double(state.diagnostics.residual);
    record.checkpoint = struct('step', double(state.step), 'time_s', double(state.t), ...
        'finite_value_audit', all(isfinite(state.q(:))) && all(isfinite(state.qd(:))) && all(isfinite(state.qdd(:))));
    if any(~isfinite(state.q(:))) || any(~isfinite(state.qd(:))) || any(~isfinite(state.qdd(:)))
        error('cppDual:Finite', 'non-finite state at step %d', global_step);
    end
    fwrite(fid, [jsonencode(record) newline], 'char');
end
clear cleanup;
if ~movefile(tmp, char(output_jsonl), 'f'), error('cppDual:OutputRename', 'atomic rename failed'); end
end
