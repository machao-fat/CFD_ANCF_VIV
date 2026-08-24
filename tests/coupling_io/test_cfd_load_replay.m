function test_cfd_load_replay()
%TEST_CFD_LOAD_REPLAY Replay actual OpenFOAM CSV loads twice through ANCF.
% Only the first 0.5 s is used to keep this regression test lightweight.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(root,'src','structure_ancf_matlab'));
load_file = fullfile(root,'results','03_prescribed_motion','loads_non_locking.csv');
assert(exist(load_file,'file')==2,'Run the prescribed-motion CFD case first.');
T = readtable(load_file,'TextType','string');
n = min(201,height(T));
T = T(1:n,:);

% Match the dimensionless CFD benchmark scale (D=1 m) and use a robust
% short structural test case; this is an interface replay, not a riser
% calibration or a physical comparison to the D=0.028 m phase-one case.
model = vertical_ttr_case('L',1.0,'D',1.0,'dInner',0.8, ...
    'nElem',2,'nSlices',1,'topTension_N',10000,'dt',0.0025);
% Put the single CFD slice in the deformable interior rather than at a
% position-constrained endpoint. This is a test-case mapping choice only.
model.coupling.s_ref_m = 0.5;
model.static.tolerance = 1.0e-7;
model.time.newton_tolerance = 1.0e-7;
state_a = ancf_initialize(model);
state_b = ancf_initialize(model);
tmp = fullfile(tempdir,'ancf_cfd_replay_snapshot.csv');
cleanup = onCleanup(@() delete_if_exists(tmp)); %#ok<NASGU>

for k = 1:n
    writetable(T(k,:),tmp);
    [force_a,meta] = ancf_read_slice_loads_csv(tmp,model); %#ok<ASGLU>
    [force_b,~] = ancf_read_slice_loads_csv(tmp,model);
    state_a = ancf_advance_step(state_a,force_a,model.time.dt);
    state_b = ancf_advance_step(state_b,force_b,model.time.dt);
end
assert(norm(state_a.q-state_b.q,inf) < 1.0e-12);
assert(isfinite(state_a.t) && state_a.t > 0);
fprintf('PASS actual CFD load replay: %d snapshots, duplicate response error %.3e.\n', ...
    n,norm(state_a.q-state_b.q,inf));
end

function delete_if_exists(filepath)
if exist(filepath,'file'), delete(filepath); end
end
