function run_stage4f_design_v2()
%RUN_STAGE4F_DESIGN_V2 Complete corrected low-Re structural design.
root = pwd;
addpath(fullfile(root,'src','structure_ancf_matlab'));
addpath(fullfile(root,'src','structure_eb_fem_matlab'));
addpath(fullfile(root,'src','structure_ancf_matlab','stage4f_design_v2'));
c = stage4f_v2_contract();
if ~exist(c.result_dir,'dir'), mkdir(c.result_dir); end
if ~exist(c.runtime_dir,'dir'), mkdir(c.runtime_dir); end
fprintf('Stage 4F-A-v2 MATLAB start PID=%d\n',feature('getpid'));
fprintf('Target f1=%.15g Hz, L/D=%.15g\n',c.f_target,c.L/c.D);

results.schema_version = c.schema_version;
results.status = 'running';
results.generated_by = 'MATLAB R2021b existing EB and ANCF cores via v2 auxiliary layer';
results.environment.matlab_version = version;
results.environment.computer = computer;
results.environment.matlab_core_pid = feature('getpid');
results.environment.working_directory = root;
results.environment.runtime_directory = c.runtime_dir;
results.environment.result_directory = c.result_dir;
results.environment.openfoam_started = false;
results.contract = c;
candidateCells = cell(numel(c.mass_ratios)*numel(c.betas),1);
index = 0;
try
    for im = 1:numel(c.mass_ratios)
        for ib = 1:numel(c.betas)
            index = index+1;
            fprintf('Candidate %d/6: m*=%.0f beta=%.3g\n',index,c.mass_ratios(im),c.betas(ib));
            candidateCells{index} = stage4f_v2_candidate(c,c.mass_ratios(im),c.betas(ib));
            fprintf('  T=%.9g N, EB f1=%.9g Hz, ANCF f1=%.9g Hz, pass=%d\n', ...
                candidateCells{index}.top_tension_N, ...
                candidateCells{index}.meshes(3).eb.frequency_Hz(1), ...
                candidateCells{index}.meshes(3).ancf.frequency_Hz(1), ...
                candidateCells{index}.passes_pre_synthetic);
        end
    end
    results.candidates = vertcat(candidateCells{:});
    passed = find([results.candidates.passes_pre_synthetic]);
    if isempty(passed)
        error('run_stage4f_design_v2:NoCandidate','No candidate passed modal/static gates.');
    end
    [results.candidates.synthetic_response_passed] = deal(false);
    [results.candidates.production_candidate_passed] = deal(false);
    selectedIndex = choose_candidate(results.candidates,passed);
    selected = results.candidates(selectedIndex);
    fprintf('Selected pre-synthetic candidate: m*=%.0f beta=%.3g\n',selected.mass_ratio,selected.beta);
    results.synthetic = stage4f_v2_synthetic(c,selected);
    selected.synthetic_response_passed = results.synthetic.passes;
    selected.production_candidate_passed = selected.passes_pre_synthetic && results.synthetic.passes;
    results.candidates(selectedIndex) = selected;
    results.selected_candidate_index = selectedIndex;
    results.selected_candidate = selected;
    results.selection.not_based_on_expected_amplitude = true;
    results.selection.priority = {'static_and_dynamic_stability','ANCF_EB_consistency', ...
        'mesh_convergence','parameter_simplicity','moderate_mass_ratio','computational_cost','smaller_T_over_EA'};
    results.selection.method = ['all hard gates first; consistency and mesh metrics binned at gate-relevant precision; ', ...
        'then prefer beta=0.01 and moderate m*=5'];
    results.status = ternary(selected.production_candidate_passed,'completed','failed_synthetic_gate');
    results.stop_conditions_triggered = {};
    if ~selected.production_candidate_passed
        results.stop_conditions_triggered = {'synthetic_response_immediate_divergence_or_nonfinite'};
    end
    results.matlab_gate_passed = selected.production_candidate_passed;
    save(fullfile(c.result_dir,'stage4f_v2_results.mat'),'results','-v7.3');
    selectedStatePath = results.selected_candidate.meshes(3).static.checkpoint_path;
    results.selected_checkpoint_path = selectedStatePath;
    stage4f_v2_write_json(fullfile(c.result_dir,'matlab_stage4f_v2_results.json'),results);
    if ~results.matlab_gate_passed
        error('run_stage4f_design_v2:SyntheticGate','Selected synthetic response failed.');
    end
    fprintf('Stage 4F-A-v2 MATLAB completed successfully.\n');
catch exc
    failure.status = 'failed';
    failure.identifier = exc.identifier;
    failure.message = exc.message;
    failure.completed_candidate_count = index;
    failure.matlab_core_pid = feature('getpid');
    failure.openfoam_started = false;
    stage4f_v2_write_json(fullfile(c.result_dir,'matlab_failure.json'),failure);
    rethrow(exc);
end
end

function selectedIndex = choose_candidate(candidates,passed)
preferred = find(arrayfun(@(x) x.mass_ratio==5 && abs(x.beta-0.01)<1e-14,candidates),1);
if ~isempty(preferred) && ismember(preferred,passed)
    selectedIndex = preferred;
    return;
end
score = zeros(numel(passed),5);
for k = 1:numel(passed)
    item = candidates(passed(k));
    cross = max(item.meshes(3).relative_frequency_difference);
    mesh = max([item.mesh_convergence.eb_relative_frequency_change; ...
        item.mesh_convergence.ancf_relative_frequency_change]);
    score(k,:) = [round(cross,3),round(mesh,3),abs(item.beta-0.01),abs(item.mass_ratio-5),item.T_over_EA];
end
[~,order] = sortrows(score,[1,2,3,4,5]);
selectedIndex = passed(order(1));
end

function value = ternary(condition,trueValue,falseValue)
if condition, value=trueValue; else, value=falseValue; end
end
