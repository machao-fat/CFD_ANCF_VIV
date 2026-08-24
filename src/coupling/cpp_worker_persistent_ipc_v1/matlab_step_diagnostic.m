function matlab_step_diagnostic(source_mat, output_json, fixture_txt)
%MATLAB_STEP_DIAGNOSTIC Export intermediate values for MATLAB/C++ parity audit.
% This is read-only with respect to the source checkpoint and does not start CFD.
loaded = load(char(source_mat), 'state');
state = loaded.state;
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(genpath(fullfile(root, 'structure_ancf_matlab')));
q = state.q(:); qd = state.qd(:); qdd = state.qdd(:);
dt = state.model.time.dt;
beta = state.model.time.beta; gamma = state.model.time.gamma;
q_pred = q + dt*qd + dt^2*(0.5-beta)*qdd;
qd_pred = qd + dt*(1-gamma)*qdd;
[internal_before, tangent_before] = ancf_internal_force_tangent(q, state.model);
mass = state.model.mass_matrix;
candidate = state;
candidate = ancf_advance_step(candidate, state.last_slice_force_N, dt);
[internal_after, tangent_after] = ancf_internal_force_tangent(candidate.q, candidate.model);

write_text_fixture(fixture_txt, state, q, qd, qdd, mass);
record = struct();
record.source_step = double(state.step); record.source_time_s = double(state.t);
record.dt_s = double(dt); record.beta = double(beta); record.gamma = double(gamma);
record.q = q(:).'; record.qdot = qd(:).'; record.qddot = qdd(:).';
record.predictor = q_pred(:).'; record.velocity_predictor = qd_pred(:).';
record.internal_before = internal_before(:).'; record.internal_after = internal_after(:).';
record.tangent_before = tangent_before(:).'; record.tangent_after = tangent_after(:).';
record.q_after = candidate.q(:).'; record.qdot_after = candidate.qd(:).';
record.qddot_after = candidate.qdd(:).'; record.residual = double(candidate.diagnostics.residual);
record.iterations = double(candidate.diagnostics.iterations);
record.mass = mass(:).';
record.finite_value_audit = all(isfinite([record.q record.qdot record.qddot record.q_after record.qdot_after record.qddot_after]));
tmp = [char(output_json) '.tmp'];
fid = fopen(tmp, 'w', 'n', 'UTF-8');
if fid < 0, error('cppDual:DiagnosticOutput', 'cannot open diagnostic output'); end
fwrite(fid, [jsonencode(record) newline], 'char'); fclose(fid);
if ~movefile(tmp, char(output_json), 'f'), error('cppDual:DiagnosticRename', 'atomic rename failed'); end
end

function write_text_fixture(path, state, q, qd, qdd, mass)
model = state.model;
fid = fopen(path, 'w', 'n', 'UTF-8');
if fid < 0, error('cppDual:FixtureOutput', 'cannot open C++ fixture'); end
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, '%.17g %.17g %.17g %d %d %.17g %.17g %.17g %.17g %.17g %.17g %.17g %d %d %.17g\n', ...
    model.geometry.L, model.geometry.D, model.geometry.d, ...
    model.geometry.n_elem, numel(model.coupling.s_ref_m), model.material.E, ...
    model.material.rho, model.fluid.rho, model.fluid.g, model.time.beta, ...
    model.time.gamma, model.time.newton_tolerance, model.integration.n_gauss, ...
    model.time.max_newton, model.time.dt);
fprintf(fid, '%.17g ', model.coupling.s_ref_m); fprintf(fid, '\n');
fprintf(fid, '%.17g ', q); fprintf(fid, '\n');
fprintf(fid, '%.17g ', qd); fprintf(fid, '\n');
fprintf(fid, '%.17g ', qdd); fprintf(fid, '\n');
fprintf(fid, '%.17g ', state.base_load); fprintf(fid, '\n');
fprintf(fid, '%.17g ', mass(:)); fprintf(fid, '\n');
fprintf(fid, '%.17g ', state.last_slice_force_N(:)); fprintf(fid, '\n');
clear cleanup;
end
