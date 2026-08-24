function export_record = matlab_dual_run_export(source_mat, output_json, global_step, bridge_step, time_s, integer_tick, slice_force_N)
%MATLAB_DUAL_RUN_EXPORT Export one read-only MATLAB golden step for C++ dual-run.
% This helper never starts CFD and never mutates the source checkpoint.  It
% evaluates the existing ANCF core from a copied in-memory state, then writes
% a canonical JSON record consumed by dual_run.py.
if nargin < 7 || isempty(slice_force_N), slice_force_N = []; end
source_mat = char(source_mat); output_json = char(output_json);
if ~isfile(source_mat), error('cppDual:SourceMissing', 'source checkpoint is missing'); end
if ~(isscalar(global_step) && isscalar(bridge_step) && isscalar(time_s) && isscalar(integer_tick))
    error('cppDual:Identity', 'identity arguments must be scalar');
end
loaded = load(source_mat, 'state');
if ~isfield(loaded, 'state'), error('cppDual:SourceSchema', 'source checkpoint has no state variable'); end
state = loaded.state;
if ~isfield(state, 'model') || ~isfield(state, 'q') || ~isfield(state, 'qd') || ~isfield(state, 'qdd')
    error('cppDual:StateSchema', 'source state is incomplete');
end
ancf_root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(genpath(fullfile(ancf_root, 'structure_ancf_matlab')));
q_n = state.q(:); qd_n = state.qd(:); qdd_n = state.qdd(:);
dt = state.model.time.dt;
beta = state.model.time.beta; gamma = state.model.time.gamma;
q_pred = q_n + dt*qd_n + dt^2*(0.5-beta)*qdd_n;
qd_pred = qd_n + dt*(1-gamma)*qdd_n;
if isempty(slice_force_N), slice_force_N = zeros(numel(state.model.coupling.s_ref_m), 3); end
Qext = state.base_load + ancf_external_load(state, slice_force_N);
[internal_before, ~] = ancf_internal_force_tangent(q_n, state.model);
candidate = state;
candidate = ancf_advance_step(candidate, slice_force_N, dt);
[internal_after, ~] = ancf_internal_force_tangent(candidate.q, candidate.model);
record = struct();
record.run_id = 'matlab_dual_golden'; record.case_id = 'matlab_dual_case';
record.global_step = double(global_step); record.case_local_bridge_step = double(bridge_step);
record.time_s = double(time_s); record.integer_tick = double(integer_tick);
record.q = candidate.q(:).'; record.qdot = candidate.qd(:).'; record.qddot = candidate.qdd(:).';
record.internal_force = internal_after(:).'; record.external_force = Qext(:).';
record.generalized_force = Qext(:).'; record.predictor = q_pred(:).';
record.corrector = candidate.q(:).'; record.residual = double(candidate.diagnostics.residual);
record.source_q = q_n(:).'; record.source_qdot = qd_n(:).'; record.source_qddot = qdd_n(:).';
record.source_internal_force = internal_before(:).'; record.dt_s = double(dt);
record.checkpoint = struct('step', double(candidate.step), 'time_s', double(candidate.t), ...
    'finite_value_audit', all(isfinite(candidate.q(:))) && all(isfinite(candidate.qd(:))) && all(isfinite(candidate.qdd(:))));
if any(~isfinite(candidate.q(:))) || any(~isfinite(candidate.qd(:))) || any(~isfinite(candidate.qdd(:)))
    error('cppDual:Finite', 'MATLAB golden state contains NaN/Inf');
end
encoded = jsonencode(record);
tmp = [output_json '.tmp'];
fid = fopen(tmp, 'w', 'n', 'UTF-8');
if fid < 0, error('cppDual:Output', 'cannot open output'); end
fwrite(fid, [encoded newline], 'char'); fclose(fid);
if ~movefile(tmp, output_json, 'f'), error('cppDual:OutputRename', 'atomic rename failed'); end
export_record = record;
end
