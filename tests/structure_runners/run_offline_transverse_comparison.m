function metrics = run_offline_transverse_comparison(result_dir)
%RUN_OFFLINE_TRANSVERSE_COMPARISON EB/ANCF with one identical prescribed Fy.
%
% This is a structural/interface diagnostic, not an online FSI validation.
% It deliberately keeps the physical steel modulus, uses a riser-like L/D,
% suppresses body forces consistently in both branches, and sends Fx=Fz=0.

root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(root,'src','structure_eb_fem_matlab'));
addpath(fullfile(root,'src','structure_ancf_matlab'));
if nargin < 1 || isempty(result_dir)
    result_dir = fullfile(root,'results','04_eb_ancf_physical_comparison', ...
        'offline_transverse_same_fy');
end
if ~exist(result_dir,'dir'), mkdir(result_dir); end

L = 150.0;
D = 1.0;
dInner = 0.9;
nElem = 10;
topTension = 1.0e6;
E = 2.07e11;
dt = 0.01;
tEnd = 40.0;
forceAmplitude = 100.0;
forceFrequency = 0.165;
rampDuration = 10.0;
zetaTarget = 0.01;
sRef = L/2;

ebModel = eb_ttr_case('L',L,'D',D,'dInner',dInner, ...
    'nElem',nElem,'nSlices',1,'topTension_N',topTension, ...
    'youngs_modulus_Pa',E,'dt',dt);
ebModel.physics.include_gravity = false;
ebModel.physics.include_buoyancy = false;
ebModel.pretension.ancf_initial_weight_Npm = 0.0;
ebModel.coupling.s_ref_m = sRef;
ebModal = eb_modal_analysis(ebModel,4);
f1EB = ebModal.frequency_Hz(1);
rayleighAlpha = 2*zetaTarget*(2*pi*f1EB);
ebModel.damping.rayleigh_alpha = rayleighAlpha;
ebState = eb_initialize(ebModel);

ancfModel = vertical_ttr_case('L',L,'D',D,'dInner',dInner, ...
    'nElem',nElem,'nSlices',1,'topTension_N',topTension, ...
    'youngs_modulus_Pa',E,'dt',dt);
ancfModel.physics.include_gravity = false;
ancfModel.physics.include_buoyancy = false;
ancfModel.damping.rayleigh_alpha = rayleighAlpha;
ancfModel.damping.rayleigh_beta = 0.0;
ancfModel.coupling.s_ref_m = sRef;
ancfState = ancf_initialize(ancfModel);
[~,KAncf] = ancf_internal_force_tangent(ancfState.q,ancfState.model);
[~,freeAncf] = ancf_constraints(ancfState.model);
lambdaAncf = real(eig(KAncf(freeAncf,freeAncf), ...
    ancfState.model.mass_matrix(freeAncf,freeAncf)));
lambdaAncf = sort(lambdaAncf(isfinite(lambdaAncf) & lambdaAncf > 1.0e-10));
f1Ancf = sqrt(lambdaAncf(1))/(2*pi);

nStep = round(tEnd/dt);
time_s = (1:nStep).'*dt;
force_y_N = zeros(nStep,1);
eb_y_m = zeros(nStep,1);
ancf_y_m = zeros(nStep,1);
eb_vy_mps = zeros(nStep,1);
ancf_vy_mps = zeros(nStep,1);
eb_x_m = zeros(nStep,1);
ancf_x_m = zeros(nStep,1);
ancf_relative_residual = zeros(nStep,1);

for step = 1:nStep
    t = time_s(step);
    if t < rampDuration
        ramp = 0.5*(1-cos(pi*t/rampDuration));
    else
        ramp = 1.0;
    end
    force_y_N(step) = forceAmplitude*ramp*sin(2*pi*forceFrequency*t);
    appliedForce = [0.0,force_y_N(step),0.0];
    ebState = eb_advance_step(ebState,appliedForce,dt);
    ancfState = ancf_advance_step(ancfState,appliedForce,dt);
    ebMotion = eb_slice_motion(ebState);
    ancfMotion = ancf_slice_motion(ancfState);
    eb_y_m(step) = ebMotion.y_m(1);
    ancf_y_m(step) = ancfMotion.y_m(1);
    eb_vy_mps(step) = ebMotion.vy_mps(1);
    ancf_vy_mps(step) = ancfMotion.vy_mps(1);
    eb_x_m(step) = ebMotion.x_m(1);
    ancf_x_m(step) = ancfMotion.x_m(1);
    ancf_relative_residual(step) = ancfState.diagnostics.relative_residual;
    if any(~isfinite([eb_y_m(step),ancf_y_m(step),eb_vy_mps(step), ...
            ancf_vy_mps(step),ancf_relative_residual(step)]))
        error('run_offline_transverse_comparison:NonFinite', ...
            'Non-finite structural response at step %d.',step);
    end
end

comparison = table(time_s,force_y_N,eb_x_m,ancf_x_m,eb_y_m,ancf_y_m, ...
    eb_vy_mps,ancf_vy_mps,abs(eb_y_m-ancf_y_m), ...
    ancf_relative_residual, ...
    'VariableNames',{'time_s','force_y_N','eb_x_m','ancf_x_m','eb_y_m', ...
    'ancf_y_m','eb_vy_mps','ancf_vy_mps','abs_y_difference_m', ...
    'ancf_relative_residual'});
writetable(comparison,fullfile(result_dir,'offline_transverse_same_fy.csv'));

window = time_s >= tEnd/2;
rmsEB = sqrt(mean(eb_y_m(window).^2));
rmsAncf = sqrt(mean(ancf_y_m(window).^2));
rmsDifference = sqrt(mean((eb_y_m(window)-ancf_y_m(window)).^2));
relativeRMSE = rmsDifference/max([rmsEB,rmsAncf,eps]);
peakEB = max(abs(eb_y_m));
peakAncf = max(abs(ancf_y_m));
maxInline = max(abs([eb_x_m;ancf_x_m]));
modalRelativeDifference = abs(f1EB-f1Ancf)/f1EB;
maxSlopeEB = max(abs([ebState.output.slope_x(:);ebState.output.slope_y(:)]));
maxSlopeAncf = max(sqrt(sum(ancfState.output.tangent(:,1:2).^2,2)));

area = pi*(D^2-dInner^2)/4;
areaDisplaced = pi*D^2/4;
submergedWeight = (7850*area-1025*areaDisplaced)*9.81;
bottomTensionIfBodyIncluded = topTension-submergedWeight*L;
EI = E*pi*(D^4-dInner^4)/64;

metrics = struct();
metrics.schema_version = '0.1.0';
metrics.status = 'offline_structural_diagnostic';
metrics.scope = ['Identical prescribed integrated Fy applied offline to EB and ANCF; ', ...
    'not an online CFD-FSI or lock-in validation.'];
metrics.parameters = struct('L_m',L,'D_m',D,'dInner_m',dInner, ...
    'L_over_D',L/D,'nElem',nElem,'nSlices',1,'s_ref_m',sRef, ...
    'youngs_modulus_Pa',E,'top_tension_N',topTension,'dt_s',dt, ...
    'duration_s',tEnd,'force_amplitude_N',forceAmplitude, ...
    'force_frequency_Hz',forceFrequency,'smooth_ramp_duration_s',rampDuration, ...
    'target_damping_ratio_first_mode',zetaTarget, ...
    'rayleigh_alpha_1ps',rayleighAlpha,'rayleigh_beta_s',0.0, ...
    'body_forces_enabled',false,'load_components','Fy only, Fx=Fz=0', ...
    'force_representation','integrated_N');
metrics.dimensionless_audit = struct('mass_ratio_structure_to_displaced_fluid', ...
    7850*area/(1025*areaDisplaced),'tension_to_bending_ratio_TL2_over_EI', ...
    topTension*L^2/EI,'submerged_weight_Npm_if_enabled',submergedWeight, ...
    'bottom_tension_N_if_body_force_enabled',bottomTensionIfBodyIncluded);
metrics.modal = struct('eb_first_frequency_Hz',f1EB, ...
    'ancf_first_frequency_Hz',f1Ancf, ...
    'relative_frequency_difference',modalRelativeDifference, ...
    'forcing_over_eb_first_frequency',forceFrequency/f1EB);
metrics.response = struct('statistics_window_s',[tEnd/2,tEnd], ...
    'eb_rms_y_m',rmsEB,'ancf_rms_y_m',rmsAncf, ...
    'relative_y_rmse',relativeRMSE,'eb_peak_abs_y_m',peakEB, ...
    'ancf_peak_abs_y_m',peakAncf,'eb_peak_A_over_D',peakEB/D, ...
    'ancf_peak_A_over_D',peakAncf/D,'max_inline_abs_m',maxInline, ...
    'final_eb_max_slope',maxSlopeEB,'final_ancf_max_slope',maxSlopeAncf, ...
    'max_ancf_relative_newton_residual',max(ancf_relative_residual));
metrics.acceptance = struct('visible_response_above_1e_minus_5_m', ...
    min(peakEB,peakAncf) > 1.0e-5, ...
    'transverse_projection_exact',maxInline < 1.0e-14, ...
    'modal_frequency_difference_below_0p1_percent',modalRelativeDifference < 1.0e-3, ...
    'time_history_relative_rmse_below_1_percent',relativeRMSE < 0.01, ...
    'ancf_newton_relative_residual_below_1e_minus_7', ...
    max(ancf_relative_residual) < 1.0e-7);
acceptFields = struct2array(metrics.acceptance);
metrics.acceptance.all_offline_diagnostic_checks_pass = all(acceptFields);
metrics.files = struct('time_history_csv','offline_transverse_same_fy.csv', ...
    'metrics_json','offline_transverse_same_fy_metrics.json');

jsonPath = fullfile(result_dir,'offline_transverse_same_fy_metrics.json');
fid = fopen(jsonPath,'w','n','UTF-8');
if fid < 0, error('run_offline_transverse_comparison:Write','Cannot open %s.',jsonPath); end
cleanup = onCleanup(@() fclose(fid));
fwrite(fid,jsonencode(metrics),'char');
fwrite(fid,newline,'char');
clear cleanup

fprintf(['PASS offline same-Fy comparison: f1 EB/ANCF %.6g/%.6g Hz, ', ...
    'peak y %.6g/%.6g m, relative RMSE %.3e.\n'], ...
    f1EB,f1Ancf,peakEB,peakAncf,relativeRMSE);
end
