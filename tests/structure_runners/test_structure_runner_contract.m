function test_structure_runner_contract
%TEST_STRUCTURE_RUNNER_CONTRACT Exercise both persistent branches in MATLAB.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(root,'src','coupling','structure_runners'));
addpath(fullfile(root,'src','structure_ancf_matlab'));
addpath(fullfile(root,'src','structure_eb_fem_matlab'));

cfg = struct('L',1.0,'D',1.0,'dInner',0.9,'nElem',2,'nSlices',1, ...
    's_ref_m',0.5,'topTension_N',1.0e8,'dt',0.0025, ...
    'rayleigh_alpha',0,'rayleigh_beta',0,'newton_tolerance',1e-8);
branches = {'eb','ancf'};
reference_tensions = zeros(size(branches));
for ib = 1:numel(branches)
    runner = structure_runner(branches{ib},cfg);
    runner.initialize();
    energy0 = runner.get_energy();
    assert(isfield(energy0,'stored_energy_J') && isfield(energy0,'external_potential_energy_J'));
    assert(abs(energy0.stored_energy_J-energy0.mechanical_energy_J) <= ...
        1e-12*max(1,abs(energy0.mechanical_energy_J)), ...
        'Stored energy must include the conservative base-load potential.');
    reference_tensions(ib) = energy0.reference_tension_N;
    if strcmp(branches{ib},'eb')
        assert(abs(runner.model.pretension.ancf_initial_weight_Npm) < eps, ...
            'Body-force-free EB runner retained a cached tension gradient.');
        assert(abs(runner.state.model.matrices.T0_bottom_N-cfg.topTension_N) < 1e-12*cfg.topTension_N);
        assert(abs(runner.state.model.matrices.T0_top_N-cfg.topTension_N) < 1e-12*cfg.topTension_N);
    end
    m0 = runner.get_motion();
    assert(m0.step == 0 && abs(m0.time_s) < 1e-14);
    [mp,ap] = runner.predict(1,cfg.dt,zeros(1,3));
    assert(runner.state.step == 0,'Predictor modified persistent state.');
    [mc,ac] = runner.correct(1,cfg.dt,[10,0,0]);
    assert(runner.state.step == 1 && abs(runner.state.t-cfg.dt) < 1e-14);
    assert(all(isfinite([mp.y_m(:);mc.y_m(:)])));
    assert(isfinite(ap.initial_residual) && isfinite(ac.initial_residual));
    assert(isfinite(ac.relative_residual) && ac.relative_residual >= 0);
    checkpoint = fullfile(tempdir,['stage3_runner_',branches{ib},'.mat']);
    runner.save_checkpoint(checkpoint);
    t_before = runner.state.t;
    runner.load_checkpoint(checkpoint);
    assert(abs(runner.state.t-t_before) < 1e-14);
    for step = 2:20
        t = step*cfg.dt;
        load = [10*sin(0.1*step),0,0];
        runner.predict(step,t,load);
        [~,audit] = runner.correct(step,t,load);
        energy = runner.get_energy();
        assert(all(isfinite(struct2array(energy))),'%s energy became non-finite.',branches{ib});
        assert(isfinite(audit.initial_residual) && isfinite(audit.residual));
        assert(isfinite(energy.min_tension_N) && isfinite(energy.max_tension_N));
        assert(isfinite(energy.reference_tension_N));
        assert(energy.max_tension_N >= energy.min_tension_N);
        assert(energy.reference_tension_N > 0,'Reference tension must be positive.');
        assert(islogical(energy.compression_risk) || isnumeric(energy.compression_risk));
    end
    assert(runner.state.step == 20);
    fprintf('PASS persistent %s runner: step=%d t=%.6g y=%.6e\n', ...
        branches{ib},runner.state.step,runner.state.t,runner.get_motion().y_m(1));
    runner.finalize();
end
assert(abs(reference_tensions(1)-reference_tensions(2)) < 1e-12*cfg.topTension_N, ...
    'Body-force-free EB and ANCF runners do not share the same reference tension.');
end
