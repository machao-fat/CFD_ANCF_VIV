function summary = run_stage4f_transient_certification()
% Synthetic-load diagnostic only. This is not an FSI or VIV calculation.
root = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
addpath(fullfile(root,'src','structure_ancf_matlab'));
addpath(fullfile(root,'src','structure_ancf_matlab','stage4f_design_v2'));
outdir = fullfile(root,'results','12_stage4f_transient_certification');
rundir = fullfile(root,'runtime','stage4f_transient_certification');
if ~exist(outdir,'dir'), mkdir(outdir); end
if ~exist(rundir,'dir'), mkdir(rundir); end

% Frozen Stage 4F-A-v2.1 candidate, all in SI units.
p = struct('D_m',1,'L_m',50,'Re',100,'U_mps',1,'mass_ratio',5,'beta',0.01, ...
    'T_N',2179104.0029808935,'E_Pa',3227125779.2218256, ...
    'EA_N',481569945.41014224,'EI_Nm2',54477600.07452233, ...
    'nElem_production',16,'nElem_reference',32,'nSlices',3,'rho_kgpm3',1000, ...
    'load_Cy_amplitude',0.30,'load_frequency_Hz',0.18181818181818182, ...
    't_end_s',0.025,'dt_coarse_s',0.0025,'dt_fine_s',0.00125);
c = stage4f_v2_contract();
[state0,~,~] = stage4f_v2_build_ancf(c,p.mass_ratio,p.beta,p.T_N,p.nElem_production,p.nSlices);
state0.model.material.E = p.E_Pa; state0.model.material.EA = p.EA_N; state0.model.material.EI = p.EI_Nm2;
state0.model.time.max_newton = 50; state0.model.time.newton_tolerance = 1e-8;

coarse = run_case(state0,p,p.dt_coarse_s,0,'');
checkpoint_path = fullfile(rundir,'ancf_n16_step5_checkpoint.mat');
restart = run_case(state0,p,p.dt_coarse_s,5,checkpoint_path);
fine = run_case(state0,p,p.dt_fine_s,0,'');
restart_relative_error = norm(restart.final_q-coarse.final_q,inf)/max(norm(coarse.final_q,inf),1);
dt_relative_error = norm(fine.final_q-coarse.final_q,inf)/max(norm(fine.final_q,inf),1);

stops = struct('nan_or_inf',~(coarse.all_finite && fine.all_finite && restart.all_finite), ...
    'newton_nonconvergence',~(coarse.all_converged && fine.all_converged && restart.all_converged), ...
    'significant_negative_tension',min([coarse.min_tension_N,fine.min_tension_N,restart.min_tension_N]) < -1e-6, ...
    'green_strain_over_1pct',max([coarse.max_green_strain,fine.max_green_strain,restart.max_green_strain]) > 0.01, ...
    'restart_relative_error_over_1e11',restart_relative_error > 1e-11, ...
    'energy_residual_relative_over_1e3',max([coarse.energy_relative_residual,fine.energy_relative_residual,restart.energy_relative_residual]) > 1e-3);
summary = struct('schema_version','stage4f-b-a-transient-certification-1.0', ...
    'classification','synthetic_load_diagnostic_only','openfoam_started',false, ...
    'viv_claim',false,'parameters',p,'load_definition',struct( ...
    'formula','f_2D(t)=0.5*rho*U^2*D*Cy*sin(2*pi*f*t)', ...
    'units','f_2D: N/m; F_i=f_2D*(L/nSlices): N; force direction: global y', ...
    'slice_length_m',p.L_m/p.nSlices,'force_application','each slice multiplied by slice_length exactly once'), ...
    'coarse',coarse,'fine',fine,'restart',restart,'restart_relative_error',restart_relative_error, ...
    'dt_relative_final_state_error',dt_relative_error,'stop_conditions',stops, ...
    'passed',~any(structfun(@(x) logical(x),stops)));
write_json(fullfile(outdir,'stage4f_b_a_transient_certification.json'),summary);
if ~summary.passed, error('stage4f_transient_certification:StopCondition','A required stop condition was triggered.'); end
end

function r = run_case(state0,p,dt,checkpoint_step,checkpoint_path)
state = state0; nstep = round(p.t_end_s/dt); E0 = state.output.mechanical_energy_J;
work = 0; diss = 0; allconv = true; allfinite = true; minT = inf; maxstrain = 0; maxiter = 0;
for k = 1:nstep
    tmid = state.t + 0.5*dt; F = synthetic_force(p,tmid);
    qbefore = state.q; Qdyn = ancf_external_load(state,F);
    state = ancf_advance_step(state,F,dt);
    work = work + Qdyn.'*(state.q-qbefore); % midpoint force, exact generalized displacement.
    diss = diss + dt*state.qd.'*state.model.damping_matrix*state.qd;
    allconv = allconv && state.diagnostics.converged; allfinite = allfinite && all(isfinite([state.q;state.qd;state.qdd]));
    minT = min(minT,min(state.output.tension_N)); maxstrain = max(maxstrain,max(abs(state.output.axial_strain)));
    maxiter = max(maxiter,state.diagnostics.iterations);
    if checkpoint_step > 0 && k == checkpoint_step
        ancf_save_checkpoint(state,checkpoint_path); state = ancf_load_checkpoint(checkpoint_path);
    end
end
energy_residual = (state.output.mechanical_energy_J-E0) + diss - work;
r = struct('dt_s',dt,'steps',nstep,'all_finite',allfinite,'all_converged',allconv, ...
    'maximum_newton_iterations',maxiter,'min_tension_N',minT,'max_green_strain',maxstrain, ...
    'mechanical_energy_change_J',state.output.mechanical_energy_J-E0,'external_work_J',work, ...
    'damping_dissipation_J',diss,'energy_residual_J',energy_residual, ...
    'energy_relative_residual',abs(energy_residual)/max([abs(work),abs(state.output.mechanical_energy_J-E0),1]), ...
    'final_q',state.q,'final_time_s',state.t);
end

function F = synthetic_force(p,t)
f2d = 0.5*p.rho_kgpm3*p.U_mps^2*p.D_m*p.load_Cy_amplitude*sin(2*pi*p.load_frequency_Hz*t);
F = zeros(p.nSlices,3); F(:,2) = f2d*(p.L_m/p.nSlices);
end

function write_json(path,s)
fid = fopen(path,'w'); assert(fid>0,'Cannot write result JSON.');
fprintf(fid,'%s\n',jsonencode(s)); fclose(fid);
end
