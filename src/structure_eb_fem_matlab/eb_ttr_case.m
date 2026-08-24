function model = eb_ttr_case(varargin)
%EB_TTR_CASE Euler-Bernoulli transverse comparator for the ANCF TTR case.
%
% The model contains two independent small-displacement/small-rotation
% bending planes.  The global nodal order is [u,theta_u,v,theta_v] at each
% node.  Axial displacement is not a degree of freedom; the prescribed
% tension profile only contributes the linear geometric stiffness.

p = inputParser;
addParameter(p,'L',100.0,@(x) validateattributes(x,{'numeric'},{'scalar','positive'}));
addParameter(p,'D',0.028,@(x) validateattributes(x,{'numeric'},{'scalar','positive'}));
addParameter(p,'dInner',0.024,@(x) validateattributes(x,{'numeric'},{'scalar','nonnegative'}));
addParameter(p,'nElem',10,@(x) validateattributes(x,{'numeric'},{'scalar','integer','>=',2}));
addParameter(p,'nSlices',11,@(x) validateattributes(x,{'numeric'},{'scalar','integer','>=',1}));
addParameter(p,'topTension_N',2000.0,@(x) validateattributes(x,{'numeric'},{'scalar','real'}));
addParameter(p,'youngs_modulus_Pa',2.07e11,@(x) validateattributes(x,{'numeric'},{'scalar','positive','finite'}));
addParameter(p,'dt',1.0e-3,@(x) validateattributes(x,{'numeric'},{'scalar','positive'}));
addParameter(p,'pretension_mode','ancf_initial_balance',@(x) ischar(x) || isstring(x));
addParameter(p,'paper_unit_weight_Npm',[],@(x) isempty(x) || (isnumeric(x) && isscalar(x) && isreal(x)));
addParameter(p,'rayleigh_alpha',0.0,@(x) validateattributes(x,{'numeric'},{'scalar','real','finite'}));
addParameter(p,'rayleigh_beta',0.0,@(x) validateattributes(x,{'numeric'},{'scalar','real','finite'}));
parse(p,varargin{:});
v = p.Results;

if v.dInner >= v.D
    error('eb_ttr_case:Geometry','The inner diameter must be smaller than D.');
end

model = struct();
model.schema_version = '0.1.0';
model.name = 'vertical_ttr_eb_fem_v0_1';
model.kinematics = 'linear_Euler_Bernoulli_small_displacement_small_rotation';

model.geometry.L = v.L;
model.geometry.D = v.D;
model.geometry.d = v.dInner;
model.geometry.n_elem = v.nElem;
model.geometry.n_node = v.nElem + 1;
model.geometry.ndof = 4*model.geometry.n_node;

model.material.E = v.youngs_modulus_Pa;
model.material.rho = 7850.0;
model.material.area = pi*(v.D^2-v.dInner^2)/4.0;
model.material.area_displaced = pi*v.D^2/4.0;
model.material.mass_per_length = model.material.rho*model.material.area;
model.material.EA = model.material.E*model.material.area;
model.material.EI = model.material.E*pi*(v.D^4-v.dInner^4)/64.0;

model.fluid.rho = 1025.0;
model.fluid.g = 9.81;
model.physics.include_gravity = true;
model.physics.include_buoyancy = true;
model.physics.effective_submerged_weight_Npm = ...
    (model.material.rho*model.material.area - model.fluid.rho*model.material.area_displaced)*model.fluid.g;

model.boundary.bottom_position_xy = [0.0;0.0];
model.boundary.top_position_xy = [0.0;0.0];
model.boundary.bottom_position_fixed = [true;true];
model.boundary.top_position_fixed = [true;true];
% These are position constraints only.  Both end slopes/rotations remain free,
% matching the ANCF x/y position constraints rather than imposing a pinned or
% clamped slope by accident.
model.boundary.slopes_free = true;

mode = lower(char(v.pretension_mode));
if ~ismember(mode,{'ancf_initial_balance','paper_formula'})
    error('eb_ttr_case:PretensionMode','Unknown pretension mode: %s',mode);
end
model.pretension.mode = mode;
model.pretension.top_tension_N = v.topTension_N;
model.pretension.ancf_initial_weight_Npm = model.physics.effective_submerged_weight_Npm;
if isempty(v.paper_unit_weight_Npm)
    model.pretension.paper_unit_weight_Npm = model.physics.effective_submerged_weight_Npm;
else
    model.pretension.paper_unit_weight_Npm = v.paper_unit_weight_Npm;
end

model.integration.n_gauss = 5;
model.numerics.symmetrize = true;
model.time.dt = v.dt;
model.time.beta = 0.25;
model.time.gamma = 0.5;

model.damping.rayleigh_alpha = v.rayleigh_alpha;
model.damping.rayleigh_beta = v.rayleigh_beta;

model.static.distributed_load_Npm = [0.0;0.0];
model.static.external_slice_force_N = zeros(v.nSlices,3);

model.coupling.s_ref_m = linspace(0.0,v.L,v.nSlices).';
model.coupling.force_representation = 'integrated_N';
model.coupling.force_components = {'Fx_N','Fy_N','Fz_N'};
model.coupling.coordinate_system = 'G_X_IL_Y_CF_Z_BOTTOM_TO_TOP';
model.coupling.z_motion = 'reference_arc_length_only';
model.post.s_ref_m = linspace(0.0,v.L,max(101,10*v.nElem+1)).';
end
