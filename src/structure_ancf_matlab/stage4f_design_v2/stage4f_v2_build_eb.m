function model = stage4f_v2_build_eb(c,mass_ratio,beta,T,nElem,nSlices)
%STAGE4F_V2_BUILD_EB Configure the existing EB core without changing it.
if nargin < 6, nSlices = 9; end
m_s = mass_ratio*c.m_f;
m_eff = m_s+c.m_added;
EI = beta*T*c.L^2;
E = EI/c.I;
EA = E*c.A;
model = eb_ttr_case('L',c.L,'D',c.D,'dInner',c.di,'nElem',nElem, ...
    'nSlices',nSlices,'topTension_N',T,'youngs_modulus_Pa',E,'dt',0.02, ...
    'pretension_mode','ancf_initial_balance','rayleigh_alpha',0,'rayleigh_beta',0);
model.material.E = E;
model.material.EA = EA;
model.material.EI = EI;
model.material.rho = m_s/c.A;
model.material.mass_per_length = m_eff;
model.fluid.rho = c.rho_f;
model.physics.effective_submerged_weight_Npm = (m_s-c.m_f)*c.g;
model.pretension.top_tension_N = T;
model.pretension.ancf_initial_weight_Npm = model.physics.effective_submerged_weight_Npm;
model.pretension.paper_unit_weight_Npm = model.physics.effective_submerged_weight_Npm;
model.coupling.s_ref_m = ((0:nSlices-1).'+0.5)*c.L/nSlices;
model.static.external_slice_force_N = zeros(nSlices,3);
model.post.s_ref_m = linspace(0,c.L,501).';
model.matrices = eb_build_matrices(model);
end

