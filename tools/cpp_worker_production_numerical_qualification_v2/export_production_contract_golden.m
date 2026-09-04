function export_production_contract_golden(seed_mat, output_jsonl)
%EXPORT_PRODUCTION_CONTRACT_GOLDEN MATLAB reference trajectory for C++ V2.
% The accepted source MAT is read only.  The numerical settings below are
% applied only to the in-memory copy used by this isolated qualification.
loaded = load(char(seed_mat), 'state');
state = loaded.state;
if double(state.step) ~= 559 || abs(double(state.t) - 2.2075) > 1e-12
    error('cppQualification:SourceIdentity', 'seed must be step 559 at 2.2075 s');
end
if abs(double(state.model.time.dt) - 0.00125) > 1e-15
    error('cppQualification:Dt', 'global dt must equal 0.00125 s');
end
if ~isequal(state.model.mass_matrix, state.model.mass_matrix.')
    error('cppQualification:Mass', 'seed mass matrix must be symmetric');
end
% Pin the production nonlinear/internal-force contract; do not change mass
% quadrature, physics, damping, geometry, material, forces, or time step.
state.model.integration.n_gauss = 3;
state.model.time.max_newton = 40;
project_root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(genpath(fullfile(project_root, 'src', 'structure_ancf_matlab')));
run_id = 'cpp_worker_production_numerical_qualification_v2_2_001';
case_id = 'cpp_worker_production_numerical_qualification_v2_2_case_001';
slice_force = state.last_slice_force_N;
dt = double(state.model.time.dt);
tmp = [char(output_jsonl) '.tmp'];
fid = fopen(tmp, 'w', 'n', 'UTF-8');
if fid < 0, error('cppQualification:Output', 'cannot create golden output'); end
cleanup = onCleanup(@() fclose(fid));
for index = 1:40
    q_n = state.q(:); qd_n = state.qd(:); qdd_n = state.qdd(:);
    q_pred = q_n + dt*qd_n + dt^2*(0.5-state.model.time.beta)*qdd_n;
    Qext = state.base_load + ancf_external_load(state, slice_force);
    state = ancf_advance_step(state, slice_force, dt);
    [internal_after, ~] = ancf_internal_force_tangent(state.q, state.model);
    if any(~isfinite(state.q(:))) || any(~isfinite(state.qd(:))) || any(~isfinite(state.qdd(:)))
        error('cppQualification:Finite', 'non-finite MATLAB state at step %d', 559 + index);
    end
    record = struct();
    record.run_id = run_id; record.case_id = case_id;
    record.global_step = 559 + index; record.case_local_bridge_step = index;
    record.time_s = double(state.t); record.integer_tick = round(double(state.t)*1e9);
    record.sequence = index; record.request_id = 206000 + index;
    record.transaction_id = 206000000 + index; record.return_code = 0;
    record.gauss_order = 3; record.max_newton = 40; record.mass_gauss_order = 5;
    record.q = state.q(:).'; record.qdot = state.qd(:).'; record.qddot = state.qdd(:).';
    record.internal_force = internal_after(:).'; record.external_force = Qext(:).';
    record.generalized_force = Qext(:).'; record.predictor = q_pred(:).';
    record.corrector = state.q(:).'; record.residual = double(state.diagnostics.residual);
    record.iterations = double(state.diagnostics.iterations);
    record.finite_value_audit = true;
    record.checkpoint = struct('step', double(state.step), 'time_s', double(state.t));
    payload_values = [record.q record.qdot record.qddot record.internal_force ...
        record.external_force record.generalized_force record.predictor record.corrector];
    % The JSONL record is the auditable golden.  Hash its post-JSON numeric
    % representation so an independent reader reconstructs the same bytes.
    payload_roundtrip = jsondecode(jsonencode(payload_values));
    payload_bytes = typecast(double(payload_roundtrip(:)), 'uint8');
    record.payload_size_bytes = numel(payload_bytes);
    record.payload_hash = sha256_hex(payload_bytes);
    fwrite(fid, [jsonencode(record) newline], 'char');
end
clear cleanup;
if ~movefile(tmp, char(output_jsonl), 'f')
    error('cppQualification:OutputRename', 'atomic rename failed');
end
end

function hex = sha256_hex(bytes)
md = java.security.MessageDigest.getInstance('SHA-256');
md.update(int8(bytes(:)));
raw = md.digest(); out = zeros(1, numel(raw), 'uint8');
for k = 1:numel(raw)
    value = double(raw(k)); if value < 0, value = value + 256; end
    out(k) = uint8(value);
end
hex = lower(reshape(dec2hex(out, 2).', 1, []));
end
