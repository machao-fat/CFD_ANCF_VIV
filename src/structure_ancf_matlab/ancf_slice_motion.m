function motion = ancf_slice_motion(state)
%ANCF_SLICE_MOTION Return centerline motion at CFD slice locations.
H = state.model.mapping.H3;
ns = numel(state.model.coupling.s_ref_m);
xyz = reshape(H*state.q,3,ns).';
vel = reshape(H*state.qd,3,ns).';
acc = reshape(H*state.qdd,3,ns).';
motion = struct();
motion.schema_version = state.schema_version;
motion.step = state.step;
motion.coupling_iteration = 0;
motion.time_s = state.t;
motion.slice_id = (0:ns-1).';
motion.s_ref_m = state.model.coupling.s_ref_m(:);
motion.x_m = xyz(:,1); motion.y_m = xyz(:,2); motion.z_m = xyz(:,3);
motion.vx_mps = vel(:,1); motion.vy_mps = vel(:,2); motion.vz_mps = vel(:,3);
motion.ax_mps2 = acc(:,1); motion.ay_mps2 = acc(:,2); motion.az_mps2 = acc(:,3);
end
