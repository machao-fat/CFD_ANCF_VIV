function [q,diagnostics] = ancf_static_equilibrium(model,q0,Qbase)
%ANCF_STATIC_EQUILIBRIUM Load-ramped static Newton solve.
[fixed,free,values] = ancf_constraints(model);
q = q0;
q(fixed) = values(fixed);
diagnostics = struct('converged',false,'load_steps',0,'iterations',0,'residual',NaN);

for iload = 1:model.static.n_load_steps
    factor = iload/model.static.n_load_steps;
    converged = false;
    for iter = 1:model.static.max_newton
        [Q,K] = ancf_internal_force_tangent(q,model);
        R = Q - factor*Qbase;
        R(fixed) = 0;
        rnorm = norm(R(free),inf);
        if rnorm <= model.static.tolerance*max(1.0,norm(Qbase(free),inf))
            converged = true;
            break;
        end
        Kff = K(free,free);
        if rcond(Kff) < 1.0e-14
            error('ancf_static_equilibrium:Singular', ...
                'Static tangent is singular at load factor %.3f.',factor);
        end
        dq = -Kff\R(free);
        q(free) = q(free) + 0.8*dq;
        q(fixed) = values(fixed);
    end
    diagnostics.iterations = diagnostics.iterations + iter;
    diagnostics.residual = rnorm;
    diagnostics.load_steps = iload;
    if ~converged
        error('ancf_static_equilibrium:NoConvergence', ...
            'Static solve did not converge at load factor %.3f (residual %.3e).',factor,rnorm);
    end
end
diagnostics.converged = true;
end
