function test_eb_damped_newmark
%TEST_EB_DAMPED_NEWMARK Regress the damped Newmark equilibrium identity.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(root,'src','structure_eb_fem_matlab'));

dt = 2.5e-3;
model = eb_ttr_case('L',10,'D',0.2,'dInner',0.16, ...
    'nElem',4,'nSlices',1,'topTension_N',2.0e4,'dt',dt, ...
    'rayleigh_alpha',0.2,'rayleigh_beta',1.0e-4);
model.physics.include_gravity = false;
model.physics.include_buoyancy = false;
model.pretension.ancf_initial_weight_Npm = 0;
model.coupling.s_ref_m = model.geometry.L/2;
state = eb_initialize(model);

for step = 1:20
    force = [0,100*sin(0.31*step),0];
    state = eb_advance_step(state,force,dt);
    assert(state.diagnostics.relative_residual < 1.0e-10, ...
        'Damped Newmark step does not satisfy dynamic equilibrium.');
end

% The undamped path remains an equilibrium solution as well.
model0 = eb_ttr_case('L',10,'D',0.2,'dInner',0.16, ...
    'nElem',4,'nSlices',1,'topTension_N',2.0e4,'dt',dt);
model0.physics.include_gravity = false;
model0.physics.include_buoyancy = false;
model0.pretension.ancf_initial_weight_Npm = 0;
model0.coupling.s_ref_m = model0.geometry.L/2;
state0 = eb_initialize(model0);
for step = 1:20
    state0 = eb_advance_step(state0,[0,100*sin(0.31*step),0],dt);
    assert(state0.diagnostics.relative_residual < 1.0e-10);
end
fprintf('PASS damped/undamped EB Newmark equilibrium: %.3e / %.3e\n', ...
    state.diagnostics.relative_residual,state0.diagnostics.relative_residual);
end
