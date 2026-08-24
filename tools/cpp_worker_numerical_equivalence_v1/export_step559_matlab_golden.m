function export_step559_matlab_golden(seed_mat, output_jsonl)
%EXPORT_STEP559_MATLAB_GOLDEN Export the missing MATLAB golden from step 559.
% This file is preparation only. It must be run in a separately authorized
% MATLAB session; the Python numerical-equivalence stage never launches it.
loaded = load(char(seed_mat), 'state');
state = loaded.state;
if double(state.step) ~= 559 || abs(double(state.t) - 2.2075) > 1e-12
    error('cppNumerical:SourceIdentity', 'seed must be global step 559 at time 2.2075');
end
if double(state.model.integration.n_gauss) ~= 5 || double(state.model.time.max_newton) ~= 50
    error('cppNumerical:Contract', 'seed MATLAB native contract must be Gauss 5 / max_newton 50');
end
if abs(double(state.model.time.dt) - 0.00125) > 1e-15
    error('cppNumerical:Dt', 'seed dt must equal 0.00125');
end
project_root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(genpath(fullfile(project_root, 'src', 'structure_ancf_matlab')));
slice_force = state.last_slice_force_N;
dt = double(state.model.time.dt);
tmp = [char(output_jsonl) '.tmp'];
fid = fopen(tmp, 'w', 'n', 'UTF-8');
if fid < 0, error('cppNumerical:Output', 'cannot open output'); end
cleanup = onCleanup(@() fclose(fid));
for index = 1:40
    global_step = 559 + index;
    bridge_step = index;
    target_time = double(state.t) + dt;
    target_tick = round(target_time * 1e9);
    q_n = state.q(:); qd_n = state.qd(:); qdd_n = state.qdd(:);
    q_pred = q_n + dt*qd_n + dt^2*(0.5-state.model.time.beta)*qdd_n;
    Qext = state.base_load + ancf_external_load(state, slice_force);
    state = ancf_advance_step(state, slice_force, dt);
    [internal_after, ~] = ancf_internal_force_tangent(state.q, state.model);
    record = struct();
    record.run_id = 'cpp_worker_numerical_equivalence_before_cfd_001_matlab';
    record.case_id = 'cpp_worker_numerical_equivalence_before_cfd_case_001_matlab';
    record.global_step = global_step; record.case_local_bridge_step = bridge_step;
    record.time_s = target_time; record.integer_tick = target_tick;
    record.sequence = index; record.request_id = 510000 + index;
    record.transaction_id = 520000 + index; record.return_code = 0;
    record.q = state.q(:).'; record.qdot = state.qd(:).'; record.qddot = state.qdd(:).';
    record.internal_force = internal_after(:).'; record.external_force = Qext(:).';
    record.generalized_force = Qext(:).'; record.predictor = q_pred(:).';
    record.corrector = state.q(:).'; record.residual = double(state.diagnostics.residual);
    record.checkpoint = struct('step', double(state.step), 'time_s', double(state.t), ...
        'finite_value_audit', all(isfinite(state.q(:))) && all(isfinite(state.qd(:))) && all(isfinite(state.qdd(:))));
    if any(~isfinite(state.q(:))) || any(~isfinite(state.qd(:))) || any(~isfinite(state.qdd(:)))
        error('cppNumerical:Finite', 'non-finite state at step %d', global_step);
    end
    payload_values = [record.q, record.qdot, record.qddot, record.internal_force, ...
        record.external_force, record.generalized_force, record.predictor, record.corrector];
    % Hash the values after MATLAB's JSON numeric round-trip so the offline
    % validator reconstructs the identical IEEE-754 payload from JSONL.
    payload_json = jsonencode(payload_values);
    payload_roundtrip = jsondecode(payload_json);
    payload_bytes = typecast(double(payload_roundtrip(:)), 'uint8');
    record.payload_size_bytes = numel(payload_bytes);
    record.payload_hash = sha256_hex(payload_bytes);
    record.finite_value_audit = true;
    fwrite(fid, [jsonencode(record) newline], 'char');
end

clear cleanup;
if ~movefile(tmp, char(output_jsonl), 'f')
    error('cppNumerical:OutputRename', 'atomic rename failed');
end
end

function hex = sha256_hex(bytes)
md = java.security.MessageDigest.getInstance('SHA-256');
% Keep the R2021b-compatible int8 bridge for input and explicitly normalize
% the signed Java digest bytes below.
md.update(int8(bytes(:)));
jdigest = md.digest();
digest = zeros(1, numel(jdigest), 'uint8');
for k = 1:numel(jdigest)
    value = double(jdigest(k));
    if value < 0, value = value + 256; end
    digest(k) = uint8(value);
end
hex = lower(reshape(dec2hex(digest, 2).', 1, []));
end
