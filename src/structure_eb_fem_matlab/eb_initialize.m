function state = eb_initialize(model)
%EB_INITIALIZE Assemble matrices and solve the prescribed transverse static state.
if nargin < 1 || isempty(model), model = eb_ttr_case(); end
if any(diff(model.coupling.s_ref_m) < 0) || model.coupling.s_ref_m(1) < 0 || ...
        model.coupling.s_ref_m(end) > model.geometry.L
    error('eb_initialize:Mapping','Slice arc lengths must be monotone in [0,L].');
end
model.mapping = eb_build_mapping(model);
model.matrices = eb_build_matrices(model);
[fixed,free,values] = eb_constraints(model);
Qdist = eb_consistent_load(model,model.static.distributed_load_Npm);
Qslice = eb_external_load(model,model.static.external_slice_force_N);
Qbase = Qdist+Qslice;
q = zeros(model.geometry.ndof,1); q(fixed) = values(fixed);
K = model.matrices.K; Kff = K(free,free);
if rcond(Kff) < 1.0e-14
    error('eb_initialize:Singular','Free-free EB stiffness is singular or ill-conditioned.');
end
q(free) = Kff\(Qbase(free)-K(free,fixed)*values(fixed));
qd = zeros(size(q));
qdd = model.matrices.M\(Qbase-model.matrices.C*qd-K*q); qdd(fixed) = 0;
static_residual = K*q-Qbase;
state = struct();
state.schema_version = model.schema_version;
state.model = model;
state.q = q; state.qd = qd; state.qdd = qdd;
state.t = 0.0; state.step = 0;
state.last_slice_force_N = zeros(numel(model.coupling.s_ref_m),3);
state.base_load = Qbase;
state.static = struct('converged',true,'residual',norm(static_residual(free),inf),...
    'tension_mode',model.pretension.mode,'T0_bottom_N',model.matrices.T0_bottom_N,...
    'T0_top_N',model.matrices.T0_top_N);
state.diagnostics = struct('converged',true,'iterations',1,'residual',state.static.residual,'dt',0);
state.output = eb_postprocess(state);
end
