function state = ancf_advance_step(state, slice_force, dt)
%ANCF_ADVANCE_STEP Advance one structure time step with external slice load.
if nargin < 2 || isempty(slice_force)
    slice_force = zeros(numel(state.model.coupling.s_ref_m),3);
end
if nargin < 3 || isempty(dt)
    dt = state.model.time.dt;
end
if ~(isscalar(dt) && dt > 0)
    error('ancf_advance_step:TimeStep', 'dt must be a positive scalar.');
end

model = state.model;
[fixed,free,values] = ancf_constraints(model);
Qcfd = ancf_external_load(state,slice_force);
Qext = state.base_load + Qcfd;
M = model.mass_matrix;
C = model.damping_matrix;
beta = model.time.beta;
gamma = model.time.gamma;

q_n = state.q;
qd_n = state.qd;
qdd_n = state.qdd;
q_pred = q_n + dt*qd_n + dt^2*(0.5-beta)*qdd_n;
qd_pred = qd_n + dt*(1-gamma)*qdd_n;
q = q_pred;
q(fixed) = values(fixed);
converged = false;
initial_rnorm = NaN;
residual_scale = max(1.0,norm(Qext(free),inf));

for iter = 1:model.time.max_newton
    qdd = (q-q_pred)/(beta*dt^2);
    qd = qd_pred + gamma*dt*qdd;
    [Qint,Kint] = ancf_internal_force_tangent(q,model);
    R = M*qdd + C*qd + Qint - Qext;
    R(fixed) = 0;
    rnorm = norm(R(free),inf);
    if iter == 1, initial_rnorm = rnorm; end
    if rnorm <= model.time.newton_tolerance*max(1.0,norm(Qext(free),inf))
        converged = true;
        break;
    end
    Keff = M/(beta*dt^2) + C*gamma/(beta*dt) + Kint;
    dq = -Keff(free,free)\R(free);
    q(free) = q(free) + dq;
    q(fixed) = values(fixed);
end

if ~converged && model.time.fail_on_nonconvergence
    error('ancf_advance_step:NoConvergence', ...
        'Newton did not converge at t=%.6g s; residual %.3e after %d iterations.', ...
        state.t+dt,rnorm,iter);
end

qdd = (q-q_pred)/(beta*dt^2);
qd = qd_pred + gamma*dt*qdd;
state.q = q;
state.qd = qd;
state.qdd = qdd;
state.t = state.t + dt;
state.step = state.step + 1;
state.last_slice_force_N = slice_force;
state.diagnostics = struct('converged',converged,'iterations',iter, ...
    'initial_residual',initial_rnorm,'residual',rnorm, ...
    'residual_scale',residual_scale, ...
    'initial_relative_residual',initial_rnorm/max(residual_scale,eps), ...
    'relative_residual',rnorm/max(residual_scale,eps), ...
    'tolerance_relative',model.time.newton_tolerance,'dt',dt);
state.output = ancf_postprocess(state);
end
