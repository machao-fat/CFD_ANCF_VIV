function audit = stage4f_v2_static_metrics(state,T,EA,checkpointPath)
%STAGE4F_V2_STATIC_METRICS Gate-ready static and checkpoint diagnostics.
out = state.output;
transverseSlope = sqrt(out.tangent(:,1).^2+out.tangent(:,2).^2) ./ max(abs(out.tangent(:,3)),eps);
audit.converged = logical(state.static.converged);
audit.load_steps = state.static.load_steps;
audit.iterations = state.static.iterations;
audit.residual_N = state.static.residual;
audit.q_all_finite = all(isfinite(state.q));
audit.node_positions_all_finite = all(isfinite(state.q(reshape([6*(0:state.model.geometry.n_node-1)+1; ...
    6*(0:state.model.geometry.n_node-1)+2;6*(0:state.model.geometry.n_node-1)+3],[],1))));
audit.maximum_transverse_slope = max(transverseSlope);
audit.maximum_green_strain = max(abs(out.axial_strain));
audit.minimum_tension_N = min(out.tension_N);
audit.maximum_tension_N = max(out.tension_N);
audit.negative_tension_fraction = mean(out.tension_N < 0);
audit.large_range_negative_tension = audit.negative_tension_fraction > 0.05;
audit.T_over_EA = T/EA;
[fixed,free] = ancf_constraints(state.model);
[~,K] = ancf_internal_force_tangent(state.q,state.model);
audit.tangent_condition_number = cond(K(free,free));
ancf_save_checkpoint(state,checkpointPath);
loaded = ancf_load_checkpoint(checkpointPath);
audit.checkpoint_path = checkpointPath;
audit.checkpoint_bytes = dir(checkpointPath).bytes;
audit.checkpoint_reload_q_inf_error = norm(loaded.q-state.q,inf);
audit.checkpoint_passed = audit.checkpoint_reload_q_inf_error <= 1e-12;
audit.passes = audit.converged && audit.q_all_finite && audit.node_positions_all_finite && ...
    audit.maximum_green_strain <= 0.01 && ~audit.large_range_negative_tension && ...
    audit.checkpoint_passed && isfinite(audit.tangent_condition_number);
end

