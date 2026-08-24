function state = ancf_initialize(model)
%ANCF_INITIALIZE Initialize the vertical TTR ANCF solver state.
if nargin < 1 || isempty(model)
    model = vertical_ttr_case();
end
if model.geometry.n_node ~= model.geometry.n_elem + 1
    error('ancf_initialize:Geometry', 'n_node must equal n_elem+1.');
end
if any(diff(model.coupling.s_ref_m) < 0) || model.coupling.s_ref_m(1) < 0 || ...
        model.coupling.s_ref_m(end) > model.geometry.L
    error('ancf_initialize:Mapping', 'Slice reference arc lengths must be monotonic in [0,L].');
end

model.mapping = ancf_build_mapping(model);
model.mass_matrix = ancf_mass_matrix(model);
[Qbody,Qtop,Qbase] = ancf_base_load(model);
Qbase = Qbase + ancf_external_load(model,model.static.external_slice_force_N);
q0 = ancf_initial_configuration(model);
[q,static_diag] = ancf_static_equilibrium(model,q0,Qbase);
[~,Kref] = ancf_internal_force_tangent(q,model);
model.damping_matrix = model.damping.rayleigh_alpha*model.mass_matrix + ...
    model.damping.rayleigh_beta*Kref;

state = struct();
state.schema_version = model.schema_version;
state.model = model;
state.q = q;
state.qd = zeros(model.geometry.ndof,1);
state.qdd = zeros(model.geometry.ndof,1);
state.t = 0.0;
state.step = 0;
state.last_slice_force_N = zeros(numel(model.coupling.s_ref_m),3);
state.base_load = Qbase;
state.body_load = Qbody;
state.top_load = Qtop;
state.static = static_diag;
state.diagnostics = struct('converged',true,'iterations',0,'residual',0,'dt',0);
state.output = ancf_postprocess(state);
end
