function report = stage4f_b3_equilibrate(outputPath, sliceForce)
%STAGE4F_B3_EQUILIBRATE Build a wet ANCF state in measured mean-load equilibrium.
% This is an isolated Stage 4F-B-v3 helper.  It does not alter ANCF core code.
if ~(isnumeric(sliceForce) && isequal(size(sliceForce),[3,3]) && all(isfinite(sliceForce(:))))
    error('stage4f_b3_equilibrate:Force','sliceForce must be finite 3-by-3 integrated loads.');
end
addpath(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(fileparts(fileparts(mfilename('fullpath'))),'stage4f_design_v2'));
c = stage4f_v2_contract();
[seed,Mwet,~] = stage4f_v2_build_ancf(c,5,0.01,2179104.0029808935,16,3);
model = seed.model;
model.static.external_slice_force_N = sliceForce;
state = ancf_initialize(model);
% The static configuration is mass-independent; restore the verified wet
% mass only after equilibrium is found for subsequent transient stepping.
state.model.mass_matrix = Mwet;
state.model.damping_matrix = zeros(size(Mwet));
state.model.time.dt = 0.0025;
state.model.time.max_newton = 50;
state.model.time.newton_tolerance = 1e-8;
state.t = 0.05;
state.step = 0;
state.qd(:) = 0;
state.qdd(:) = 0;
state.last_slice_force_N = sliceForce;
state.output = ancf_postprocess(state);
metricPath = [outputPath '.metrics_checkpoint.mat'];
metric = stage4f_v2_static_metrics(state,2179104.0029808935,state.model.material.EA,metricPath);
motion = ancf_slice_motion(state);
report = struct();
report.status = ternary(metric.passes,'passed','blocked');
report.static = metric;
report.slice_force_N = sliceForce;
report.slice_motion = struct('x_m',motion.x_m,'y_m',motion.y_m,'z_m',motion.z_m, ...
    'vx_mps',motion.vx_mps,'vy_mps',motion.vy_mps,'vz_mps',motion.vz_mps, ...
    'ax_mps2',motion.ax_mps2,'ay_mps2',motion.ay_mps2,'az_mps2',motion.az_mps2);
report.max_xy_displacement_m = max(sqrt(motion.x_m.^2 + motion.y_m.^2));
save(outputPath,'state','report','-v7');
end

function out = ternary(condition,yes,no)
if condition, out = yes; else, out = no; end
end

