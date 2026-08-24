function [state,Mwet,Madded] = stage4f_v2_build_ancf(c,mass_ratio,beta,T,nElem,nSlices)
%STAGE4F_V2_BUILD_ANCF Initialize the existing nonlinear ANCF core.
if nargin < 6, nSlices = 9; end
m_s = mass_ratio*c.m_f;
EI = beta*T*c.L^2;
E = EI/c.I;
EA = E*c.A;
model = vertical_ttr_case('L',c.L,'D',c.D,'dInner',c.di,'nElem',nElem, ...
    'nSlices',nSlices,'topTension_N',T,'youngs_modulus_Pa',E,'dt',0.02);
model.material.E = E;
model.material.EA = EA;
model.material.EI = EI;
model.material.rho = m_s/c.A;
model.material.area = c.A;
model.material.area_displaced = c.area_displaced;
model.fluid.rho = c.rho_f;
model.fluid.g = c.g;
model.integration.n_gauss = 5;
model.static.n_load_steps = 12;
model.static.max_newton = 80;
model.static.tolerance = 1e-9;
model.time.max_newton = 50;
model.time.newton_tolerance = 1e-8;
model.coupling.s_ref_m = ((0:nSlices-1).'+0.5)*c.L/nSlices;
model.static.external_slice_force_N = zeros(nSlices,3);
model.post.s_ref_m = linspace(0,c.L,501).';
state = ancf_initialize(model);

addModel = state.model;
addModel.material.rho = c.m_added/c.A;
MaddedFull = ancf_mass_matrix(addModel);
nNode = state.model.geometry.n_node;
transverse = reshape([6*(0:nNode-1)+1;6*(0:nNode-1)+2; ...
    6*(0:nNode-1)+4;6*(0:nNode-1)+5],[],1);
Madded = zeros(size(MaddedFull));
Madded(transverse,transverse) = MaddedFull(transverse,transverse);
Mwet = state.model.mass_matrix+Madded;
state.model.mass_matrix = Mwet;
state.model.damping_matrix = zeros(size(Mwet));
end

