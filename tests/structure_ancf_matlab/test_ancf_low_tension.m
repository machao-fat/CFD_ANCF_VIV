function report = test_ancf_low_tension()
%TEST_ANCF_LOW_TENSION Low-tension and large-slope structural envelope.
this_file = mfilename('fullpath');
project_root = fileparts(fileparts(fileparts(this_file)));
src = fullfile(project_root,'src','structure_ancf_matlab');
addpath(src);

model = vertical_ttr_case('L',10,'D',0.028,'dInner',0.024,'nElem',8, ...
    'nSlices',21,'topTension_N',100,'dt',1.0e-3);
model.coupling.force_representation = 'line_Npm';
model.static.external_slice_force_N(:,2) = 10.0;
state = ancf_initialize(model);

max_displacement_ratio = max(sqrt(state.output.x_m.^2 + state.output.y_m.^2))/model.geometry.L;
max_slope = max(vecnorm(state.output.tangent(:,1:2),2,2));
min_tension_N = min(state.output.tension_N);
max_tension_N = max(state.output.tension_N);
assert(state.static.converged && all(isfinite(state.q)), 'Low-tension case failed.');
assert(max_slope > 0.05, 'Low-tension case did not reach a useful nonlinear slope.');

report = struct('passed',true,'top_tension_N',model.boundary.top_tension_N, ...
    'max_displacement_ratio',max_displacement_ratio,'max_slope',max_slope, ...
    'min_tension_N',min_tension_N,'max_tension_N',max_tension_N, ...
    'has_compression',min_tension_N < 0,'static_iterations',state.static.iterations);
fprintf('PASS low-tension envelope: A/L=%.6g maxSlope=%.6g Tmin=%.6g N Tmax=%.6g N\n', ...
    max_displacement_ratio,max_slope,min_tension_N,max_tension_N);
end
