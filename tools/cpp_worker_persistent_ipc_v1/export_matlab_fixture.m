function export_matlab_fixture(source_mat, output_json)
%EXPORT_MATLAB_FIXTURE Export a read-only C++ dual-run input fixture.
% The source checkpoint is never written; output is atomically renamed.
source_mat = char(source_mat); output_json = char(output_json);
loaded = load(source_mat, 'state');
if ~isfield(loaded, 'state'), error('cppDual:StateSchema', 'missing state'); end
s = loaded.state; m = s.model;
ns = numel(m.coupling.s_ref_m);
flat_force = zeros(1, 3*ns);
if isfield(s, 'last_slice_force_N') && ~isempty(s.last_slice_force_N)
    f = s.last_slice_force_N;
    if ~isequal(size(f), [ns, 3]), error('cppDual:ForceSchema', 'slice force shape mismatch'); end
    flat_force(1:3:end) = f(:,1).';
    flat_force(2:3:end) = f(:,2).';
    flat_force(3:3:end) = f(:,3).';
end
fixture = struct();
fixture.length_m = double(m.geometry.L);
fixture.diameter_m = double(m.geometry.D);
fixture.inner_diameter_m = double(m.geometry.d);
fixture.elements = double(m.geometry.n_elem);
fixture.slices = double(ns);
fixture.slice_positions_m = m.coupling.s_ref_m(:).';
fixture.top_tension_N = double(m.boundary.top_tension_N);
fixture.youngs_modulus_Pa = double(m.material.E);
fixture.material_density = double(m.material.rho);
fixture.fluid_density = double(m.fluid.rho);
fixture.gravity = double(m.fluid.g);
fixture.beta = double(m.time.beta);
fixture.gamma = double(m.time.gamma);
fixture.newton_tolerance = double(m.time.newton_tolerance);
fixture.damping_alpha = double(m.damping.rayleigh_alpha);
fixture.damping_beta = double(m.damping.rayleigh_beta);
fixture.gauss_order = double(m.integration.n_gauss);
fixture.max_newton = double(m.time.max_newton);
fixture.dt_s = double(m.time.dt);
fixture.source_step = double(s.step);
fixture.source_time_s = double(s.t);
fixture.q = s.q(:).';
fixture.qdot = s.qd(:).';
fixture.qddot = s.qdd(:).';
fixture.base_load = s.base_load(:).';
fixture.slice_force = flat_force;
fixture.source_sha256_note = 'read-only confirm_025 committed.mat';
encoded = jsonencode(fixture);
tmp = [output_json '.tmp'];
fid = fopen(tmp, 'w', 'n', 'UTF-8');
if fid < 0, error('cppDual:Output', 'cannot open fixture'); end
fwrite(fid, [encoded newline], 'char'); fclose(fid);
if ~movefile(tmp, output_json, 'f'), error('cppDual:OutputRename', 'atomic rename failed'); end
end
