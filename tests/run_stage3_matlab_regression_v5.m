function report = run_stage3_matlab_regression_v5()
%RUN_STAGE3 MATLAB-side regression inventory for the v5 acceptance bundle.
% Each function is executed in this run and failures are retained explicitly.
this_file = mfilename('fullpath');
root = fileparts(fileparts(this_file));
addpath(genpath(fullfile(root,'src')));
addpath(genpath(fullfile(root,'tests')));

names = { ...
    'test_coupling_csv_contract', ...
    'test_cfd_load_replay', ...
    'test_ancf_convergence', ...
    'test_ancf_low_tension', ...
    'test_ancf_physics', ...
    'test_ancf_tension_sweep', ...
    'test_vertical_ttr_solver', ...
    'test_eb_damped_newmark', ...
    'test_eb_fem_verification', ...
    'test_structure_runner_contract'};
results = repmat(struct('name','','passed',false,'message','','output',[]),1,numel(names));
for i = 1:numel(names)
    results(i).name = names{i};
    try
        if nargout(names{i}) > 0
            value = feval(names{i});
        else
            feval(names{i});
            value = struct('no_return_value',true);
        end
        results(i).passed = true;
        results(i).output = value;
        results(i).message = 'completed';
    catch err
        results(i).passed = false;
        results(i).message = err.message;
        results(i).output = struct('identifier',err.identifier);
    end
end

report = struct();
report.schema_version = '0.1.0';
report.status = 'matlab_regression_completed';
report.executed_in_current_run = true;
report.tests = results;
report.passed = sum([results.passed]);
report.failed = sum(~[results.passed]);
report.total = numel(results);
out_dir = fullfile(root,'results','04_continuous_fsi');
if ~exist(out_dir,'dir'), mkdir(out_dir); end
fid = fopen(fullfile(out_dir,'stage3_v5_matlab_test_results.json'),'w');
fwrite(fid,jsonencode(report),'char');
fclose(fid);
disp(jsonencode(struct('passed',report.passed,'failed',report.failed,'total',report.total)));
end
