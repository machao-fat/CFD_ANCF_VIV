function synthetic = stage4f_v2_synthetic(c,selected)
%STAGE4F_V2_SYNTHETIC Offline-only load estimates and one real short run.
mass_ratio = selected.mass_ratio;
beta = selected.beta;
T = selected.top_tension_N;
EA = selected.EA_N;
nElem = 16;
nSlices = 9;
ebModel = stage4f_v2_build_eb(c,mass_ratio,beta,T,nElem,nSlices);
ebModal = stage4f_v2_modal_eb(ebModel,4);
s = ebModal.sample_s_m;
phi = ebModal.mode_shape(:,1);
mModal = trapz(s,selected.m_eff_kgpm*phi.^2);
omega1 = 2*pi*ebModal.frequency_Hz(1);
scenario = repmat(struct(),numel(c.Cl_amp)*numel(c.St)*3,1);
index = 0;
shapeNames = {'uniform','first_mode_in_phase','simple_traveling_wave'};
for iCl = 1:numel(c.Cl_amp)
    for iSt = 1:numel(c.St)
        for iShape = 1:numel(shapeNames)
            index = index+1;
            Cl = c.Cl_amp(iCl); St = c.St(iSt);
            f = St*c.U/c.D; omega = 2*pi*f;
            base = 0.5*c.rho_f*c.U^2*c.D*Cl;
            switch iShape
                case 1
                    spatial = ones(size(s)); phase = zeros(size(s));
                case 2
                    spatial = phi; phase = zeros(size(s));
                otherwise
                    spatial = ones(size(s)); phase = 2*pi*s/c.L;
            end
            Qsin = trapz(s,phi.*base.*spatial.*cos(phase));
            Qcos = -trapz(s,phi.*base.*spatial.*sin(phase));
            Qamp = hypot(Qsin,Qcos);
            kModal = mModal*omega1^2;
            cModal = 2*c.zeta*omega1*mModal;
            qAmp = Qamp/sqrt((kModal-mModal*omega^2)^2+(cModal*omega)^2);
            scenario(index).classification = 'synthetic_load_diagnostic_only';
            scenario(index).Cl_amp = Cl;
            scenario(index).St = St;
            scenario(index).forcing_frequency_Hz = f;
            scenario(index).load_shape = shapeNames{iShape};
            scenario(index).first_modal_generalized_force_amplitude_N = Qamp;
            scenario(index).linear_steady_max_displacement_estimate_m = qAmp;
            scenario(index).linear_steady_max_displacement_over_D = qAmp/c.D;
            scenario(index).not_VIV_prediction = true;
        end
    end
end

alpha = 2*c.zeta*omega1;
ebModel.damping.rayleigh_alpha = alpha;
ebModel.matrices = eb_build_matrices(ebModel);
ebState = eb_initialize(ebModel);
[ancfState,Mwet] = stage4f_v2_build_ancf(c,mass_ratio,beta,T,nElem,nSlices);
ancfState.model.damping.rayleigh_alpha = alpha;
ancfState.model.mass_matrix = Mwet;
ancfState.model.damping_matrix = alpha*Mwet;

dt = 0.05;
forcingFrequency = 0.18*c.U/c.D;
nSteps = ceil(2.0/forcingFrequency/dt);
sliceLength = c.L/nSlices;
lineAmplitude = 0.5*c.rho_f*c.U^2*c.D*0.3;
zeroForce = zeros(nSlices,3);
ebMotionPrev = eb_slice_motion(ebState);
ancfMotionPrev = ancf_slice_motion(ancfState);
forcePrev = zeroForce;
ebInitialEnergy = ebState.output.mechanical_energy_J;
ancfInitialEnergy = ancfState.output.mechanical_energy_J;
ebWork = 0; ancfWork = 0; ebDamping = 0; ancfDamping = 0;
ebMaxDisp = 0; ancfMaxDisp = 0; ebMaxSlope = 0; ancfMaxSlope = 0;
ebMaxStrain = 0; ancfMaxStrain = 0;
ebMinTension = inf; ebMaxTension = -inf; ancfMinTension = inf; ancfMaxTension = -inf;
for istep = 1:nSteps
    timeNext = istep*dt;
    lineForce = lineAmplitude*sin(2*pi*forcingFrequency*timeNext);
    force = zeros(nSlices,3);
    force(:,2) = lineForce*sliceLength;
    ebPower0 = ebState.qd.'*ebState.model.matrices.C*ebState.qd;
    ancfPower0 = ancfState.qd.'*ancfState.model.damping_matrix*ancfState.qd;
    ebState = eb_advance_step(ebState,force,dt);
    ancfState = ancf_advance_step(ancfState,force,dt);
    ebMotion = eb_slice_motion(ebState);
    ancfMotion = ancf_slice_motion(ancfState);
    ebWork = ebWork+sum(sum(0.5*(forcePrev+force).*[zeros(nSlices,1), ...
        ebMotion.y_m-ebMotionPrev.y_m,zeros(nSlices,1)]));
    ancfWork = ancfWork+sum(sum(0.5*(forcePrev+force).*[ancfMotion.x_m-ancfMotionPrev.x_m, ...
        ancfMotion.y_m-ancfMotionPrev.y_m,ancfMotion.z_m-ancfMotionPrev.z_m]));
    ebPower1 = ebState.qd.'*ebState.model.matrices.C*ebState.qd;
    ancfPower1 = ancfState.qd.'*ancfState.model.damping_matrix*ancfState.qd;
    ebDamping = ebDamping+0.5*(ebPower0+ebPower1)*dt;
    ancfDamping = ancfDamping+0.5*(ancfPower0+ancfPower1)*dt;
    ebMaxDisp = max(ebMaxDisp,max(abs(ebState.output.y_m)));
    ancfMaxDisp = max(ancfMaxDisp,max(abs(ancfState.output.y_m)));
    ebMaxSlope = max(ebMaxSlope,max(abs(ebState.output.slope_y)));
    tangent = ancfState.output.tangent;
    transverseSlope = sqrt(tangent(:,1).^2+tangent(:,2).^2)./max(abs(tangent(:,3)),eps);
    ancfMaxSlope = max(ancfMaxSlope,max(transverseSlope));
    ebMaxStrain = max(ebMaxStrain,0.5*max(ebState.output.slope_y.^2));
    ancfMaxStrain = max(ancfMaxStrain,max(abs(ancfState.output.axial_strain)));
    ebMinTension = min(ebMinTension,ebState.output.min_tension_N);
    ebMaxTension = max(ebMaxTension,ebState.output.max_tension_N);
    ancfMinTension = min(ancfMinTension,min(ancfState.output.tension_N));
    ancfMaxTension = max(ancfMaxTension,max(ancfState.output.tension_N));
    ebMotionPrev = ebMotion; ancfMotionPrev = ancfMotion; forcePrev = force;
end
ebEnergyChange = ebState.output.mechanical_energy_J-ebInitialEnergy;
ancfEnergyChange = ancfState.output.mechanical_energy_J-ancfInitialEnergy;
synthetic.classification = 'synthetic_load_diagnostic_only';
synthetic.not_VIV_prediction = true;
synthetic.contract.Cl_amp = c.Cl_amp;
synthetic.contract.St = c.St;
synthetic.contract.load_shapes = shapeNames;
synthetic.contract.force_definition = '0.5*rho*U^2*D*Cl_amp*sin(2*pi*f_s*t)*phi_load(s)';
synthetic.modal_scenarios = scenario;
synthetic.numerical_case.Cl_amp = 0.3;
synthetic.numerical_case.St = 0.18;
synthetic.numerical_case.load_shape = 'uniform';
synthetic.numerical_case.dt_s = dt;
synthetic.numerical_case.steps = nSteps;
synthetic.numerical_case.duration_s = nSteps*dt;
synthetic.numerical_case.slice_count = nSlices;
synthetic.eb = responseStruct(ebMaxDisp,ebMaxSlope,ebMaxStrain,ebMinTension,ebMaxTension, ...
    ebWork,ebDamping,ebEnergyChange,c.D,ebState);
synthetic.ancf = responseStruct(ancfMaxDisp,ancfMaxSlope,ancfMaxStrain,ancfMinTension,ancfMaxTension, ...
    ancfWork,ancfDamping,ancfEnergyChange,c.D,ancfState);
synthetic.comparison.maximum_displacement_relative_difference = ...
    abs(ancfMaxDisp-ebMaxDisp)/max([1e-12,abs(ancfMaxDisp),abs(ebMaxDisp)]);
synthetic.comparison.both_nonzero = ancfMaxDisp > 0 && ebMaxDisp > 0;
synthetic.comparison.both_finite = all(isfinite([ancfMaxDisp,ebMaxDisp,ancfWork,ebWork]));
synthetic.comparison.no_immediate_divergence = synthetic.comparison.both_finite && ...
    ancfState.diagnostics.converged && ebState.diagnostics.converged;
synthetic.passes = synthetic.comparison.both_nonzero && synthetic.comparison.no_immediate_divergence;
end

function out = responseStruct(maxDisp,maxSlope,maxStrain,minTension,maxTension,work,damping,dEnergy,D,state)
out.maximum_displacement_m = maxDisp;
out.maximum_displacement_over_D = maxDisp/D;
out.maximum_slope = maxSlope;
out.maximum_green_strain = maxStrain;
out.minimum_tension_N = minTension;
out.maximum_tension_N = maxTension;
out.external_work_J = work;
out.damping_dissipation_J = damping;
out.mechanical_energy_change_J = dEnergy;
out.energy_residual_J = dEnergy+damping-work;
out.energy_residual_relative = abs(out.energy_residual_J)/max([1,abs(dEnergy),abs(damping),abs(work)]);
out.final_state_finite = all(isfinite(state.q)) && all(isfinite(state.qd)) && all(isfinite(state.qdd));
out.final_step_converged = logical(state.diagnostics.converged);
end

