function motion = eb_slice_motion(state)
%EB_SLICE_MOTION Return EB transverse motion using the shared CSV schema.
H = state.model.mapping.H; ns = numel(state.model.coupling.s_ref_m);
xy = reshape(H*state.q,2,ns).';
vxy = reshape(H*state.qd,2,ns).';
axy = reshape(H*state.qdd,2,ns).';
motion = struct(); motion.schema_version = state.schema_version;
motion.step = state.step; motion.coupling_iteration = 0; motion.time_s = state.t;
motion.slice_id = (0:ns-1).'; motion.s_ref_m = state.model.coupling.s_ref_m(:);
motion.x_m = xy(:,1); motion.y_m = xy(:,2); motion.z_m = motion.s_ref_m;
motion.vx_mps = vxy(:,1); motion.vy_mps = vxy(:,2); motion.vz_mps = zeros(ns,1);
motion.ax_mps2 = axy(:,1); motion.ay_mps2 = axy(:,2); motion.az_mps2 = zeros(ns,1);
end
