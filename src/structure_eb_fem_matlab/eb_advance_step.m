function state = eb_advance_step(state,slice_force,dt)
%EB_ADVANCE_STEP Linear Newmark average-acceleration step.
if nargin < 2 || isempty(slice_force)
    slice_force = zeros(numel(state.model.coupling.s_ref_m),3);
end
if nargin < 3 || isempty(dt), dt = state.model.time.dt; end
if ~(isscalar(dt) && isfinite(dt) && dt > 0)
    error('eb_advance_step:TimeStep','dt must be a positive finite scalar.');
end
model = state.model;
[fixed,free,values] = eb_constraints(model);
M = model.matrices.M; C = model.matrices.C; K = model.matrices.K;
beta = model.time.beta; gamma = model.time.gamma;
if abs(beta-0.25) > 1e-14 || abs(gamma-0.5) > 1e-14
    error('eb_advance_step:Newmark','Comparator is frozen to beta=1/4, gamma=1/2.');
end
Qext = state.base_load + eb_external_load(state,slice_force);
qn = state.q; qdn = state.qd; qddn = state.qdd;
q_pred = qn + dt*qdn + dt^2*(0.5-beta)*qddn;
qd_pred = qdn + dt*(1-gamma)*qddn;
a0 = 1/(beta*dt^2); a1 = gamma/(beta*dt);
Keff = K+a0*M+a1*C;
% With qdd=a0*(q-q_pred) and qd=qd_pred+a1*(q-q_pred),
% equilibrium gives
%   (K+a0*M+a1*C)q = Q + a0*M*q_pred + C*(a1*q_pred-qd_pred).
% The previous C*(a1*qd_pred) term mixed velocity and displacement and
% produced a non-equilibrated response whenever Rayleigh damping was nonzero.
rhs = Qext + M*(a0*q_pred) + C*(a1*q_pred-qd_pred);
q = zeros(size(qn)); q(fixed) = values(fixed);
q(free) = Keff(free,free)\(rhs(free)-Keff(free,fixed)*values(fixed));
qdd = (q-q_pred)/(beta*dt^2);
qd = qd_pred + gamma*dt*qdd;
qdd(fixed) = 0; qd(fixed) = 0;
residual = M*qdd+C*qd+K*q-Qext; residual(fixed) = 0;
q_initial = q_pred; q_initial(fixed) = values(fixed);
qdd_initial = (q_initial-q_pred)/(beta*dt^2);
qd_initial = qd_pred + gamma*dt*qdd_initial;
residual_initial = M*qdd_initial+C*qd_initial+K*q_initial-Qext;
residual_initial(fixed) = 0;
residual_scale = max(1.0,norm(Qext(free),inf));
state.q = q; state.qd = qd; state.qdd = qdd;
state.t = state.t+dt; state.step = state.step+1;
state.last_slice_force_N = slice_force;
state.diagnostics = struct('converged',true,'iterations',1, ...
    'initial_residual',norm(residual_initial(free),inf), ...
    'residual',norm(residual(free),inf), ...
    'residual_scale',residual_scale, ...
    'initial_relative_residual',norm(residual_initial(free),inf)/residual_scale, ...
    'relative_residual',norm(residual(free),inf)/residual_scale, ...
    'tolerance_relative',0,'dt',dt);
state.output = eb_postprocess(state);
end
