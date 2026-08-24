function model = vertical_ttr_case(varargin)
%VERTICAL_TTR_CASE Default case definition for a vertical top-tensioned riser.
%
% This is a new, self-contained case definition. It deliberately does not
% call the legacy Run4v4_wu package. The first version uses a 3-D two-node
% ANCF beam and exposes a 3-D slice-force interface so that a 2-D OpenFOAM
% slice can later provide [Fx,Fy,0].

p = inputParser;
addParameter(p, 'L', 100.0, @(x) validateattributes(x, {'numeric'}, {'scalar','positive'}));
addParameter(p, 'D', 0.028, @(x) validateattributes(x, {'numeric'}, {'scalar','positive'}));
addParameter(p, 'dInner', 0.024, @(x) validateattributes(x, {'numeric'}, {'scalar','nonnegative'}));
addParameter(p, 'nElem', 10, @(x) validateattributes(x, {'numeric'}, {'scalar','integer','>=',2}));
addParameter(p, 'nSlices', 11, @(x) validateattributes(x, {'numeric'}, {'scalar','integer','>=',1}));
addParameter(p, 'topTension_N', 2000.0, @(x) validateattributes(x, {'numeric'}, {'scalar','real'}));
addParameter(p, 'youngs_modulus_Pa', 2.07e11, @(x) validateattributes(x, {'numeric'}, {'scalar','positive','finite'}));
addParameter(p, 'dt', 1.0e-3, @(x) validateattributes(x, {'numeric'}, {'scalar','positive'}));
parse(p, varargin{:});
v = p.Results;

if v.dInner >= v.D
    error('vertical_ttr_case:Geometry', 'The inner diameter d must be smaller than D.');
end

model = struct();
model.schema_version = '0.1.0';
model.name = 'vertical_ttr_ancf_v0_1';

model.geometry.L = v.L;
model.geometry.D = v.D;
model.geometry.d = v.dInner;
model.geometry.n_elem = v.nElem;
model.geometry.n_node = v.nElem + 1;
model.geometry.ndof = 6 * model.geometry.n_node;

model.material.E = v.youngs_modulus_Pa;
model.material.rho = 7850.0;
model.material.area = pi * (v.D^2 - v.dInner^2) / 4.0;
model.material.area_displaced = pi * v.D^2 / 4.0;
model.material.EA = model.material.E * model.material.area;
model.material.EI = model.material.E * pi * (v.D^4 - v.dInner^4) / 64.0;

model.fluid.rho = 1025.0;
model.fluid.g = 9.81;
model.physics.include_gravity = true;
model.physics.include_buoyancy = true;

% Internal structure coordinates use +z from bottom to top.
model.boundary.bottom_position = [0.0; 0.0; 0.0];
model.boundary.top_position = [0.0; 0.0; v.L];
model.boundary.bottom_position_fixed = [true; true; true];
% x/y are prescribed by a top guide; z is force-controlled in this MVP.
model.boundary.top_position_fixed = [true; true; false];
model.boundary.top_tension_N = v.topTension_N;

model.integration.n_gauss = 3;
model.numerics.tangent_method = 'analytic_energy';
model.numerics.symmetrize_tangent = true;

model.time.dt = v.dt;
model.time.t_end = 1.0;
model.time.beta = 0.25;
model.time.gamma = 0.5;
model.time.max_newton = 40;
model.time.newton_tolerance = 1.0e-8;
model.time.fail_on_nonconvergence = true;

model.damping.rayleigh_alpha = 0.0;
model.damping.rayleigh_beta = 0.0;

model.static.n_load_steps = 8;
model.static.max_newton = 60;
model.static.tolerance = 1.0e-9;
model.static.external_slice_force_N = zeros(v.nSlices,3);

model.coupling.s_ref_m = linspace(0.0, v.L, v.nSlices).';
model.coupling.force_representation = 'integrated_N';
model.coupling.force_components = {'Fx_N','Fy_N','Fz_N'};
model.coupling.coordinate_system = 'G_X_IL_Y_CF_Z_BOTTOM_TO_TOP';

model.post.s_ref_m = linspace(0.0, v.L, max(101, 10*v.nElem + 1)).';
end
