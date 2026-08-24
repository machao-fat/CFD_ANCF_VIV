function report = test_ancf_tension_sweep()
%TEST_ANCF_TENSION_SWEEP High/mid/low top-tension structural sweep.
this_file = mfilename('fullpath');
project_root = fileparts(fileparts(fileparts(this_file)));
src = fullfile(project_root,'src','structure_ancf_matlab');
addpath(src);

tensions = [2000,500,100];
max_slope = zeros(size(tensions));
min_tension = zeros(size(tensions));
max_tension = zeros(size(tensions));
iterations = zeros(size(tensions));
for k = 1:numel(tensions)
    model = vertical_ttr_case('L',10,'D',0.028,'dInner',0.024,'nElem',8, ...
        'nSlices',21,'topTension_N',tensions(k));
    model.coupling.force_representation = 'line_Npm';
    model.static.external_slice_force_N(:,2) = 2.0;
    state = ancf_initialize(model);
    max_slope(k) = max(vecnorm(state.output.tangent(:,1:2),2,2));
    min_tension(k) = min(state.output.tension_N);
    max_tension(k) = max(state.output.tension_N);
    iterations(k) = state.static.iterations;
    assert(state.static.converged && all(isfinite(state.q)), 'Tension case failed.');
end

report = struct('passed',true,'top_tension_N',tensions,'max_slope',max_slope, ...
    'min_tension_N',min_tension,'max_tension_N',max_tension, ...
    'static_iterations',iterations);
fprintf('PASS tension sweep: T=[%g %g %g] maxSlope=[%.4g %.4g %.4g] Tmin=[%.4g %.4g %.4g]\n', ...
    tensions,max_slope,min_tension);
end
