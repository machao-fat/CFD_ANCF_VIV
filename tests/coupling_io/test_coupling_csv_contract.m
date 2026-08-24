function test_coupling_csv_contract()
%TEST_COUPLING_CSV_CONTRACT MATLAB-side stage-two exchange tests.
% This test only exercises existing ANCF public interfaces; it does not
% modify src/structure_ancf_matlab.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(root,'src','structure_ancf_matlab'));
work = fullfile(tempdir,'cfd_ancf_csv_contract_test');
if exist(work,'dir'), rmdir(work,'s'); end
mkdir(work);
cleanup = onCleanup(@() cleanup_test_dir(work)); %#ok<NASGU>

model = vertical_ttr_case('L',1.0,'D',0.028,'dInner',0.024, ...
    'nElem',2,'nSlices',1,'topTension_N',200,'dt',1.0e-3);
state = ancf_initialize(model);

% Static-cylinder motion: the initial state is finite and has zero velocity.
motion = ancf_slice_motion(state);
static_file = fullfile(work,'motion_static.csv');
ancf_write_slice_motion_csv(motion,static_file);
T = readtable(static_file,'TextType','string');
assert(height(T)==1 && abs(double(T.y_m(1))) < 1.0e-12);
assert(abs(double(T.vy_mps(1))) < 1.0e-12);

% Prescribed sinusoidal motion: verify the exchanged kinematics and signs.
omega = 2*pi*0.16; t = 0.37; A = 0.1;
motion.step = 37; motion.time_s = t;
motion.y_m = A*sin(omega*t);
motion.vy_mps = A*omega*cos(omega*t);
motion.ay_mps2 = -A*omega^2*sin(omega*t);
sine_file = fullfile(work,'motion_sine.csv');
ancf_write_slice_motion_csv(motion,sine_file);
T = readtable(sine_file,'TextType','string');
assert(abs(double(T.y_m(1))-A*sin(omega*t)) < 1.0e-12);
assert(abs(double(T.vy_mps(1))-A*omega*cos(omega*t)) < 1.0e-12);
assert(abs(double(T.ay_mps2(1))+A*omega^2*sin(omega*t)) < 1.0e-12);

% Constant virtual force: MATLAB reads integrated N and replay is repeatable.
load_file = fullfile(work,'loads_constant.csv');
load_table = table("0.1.0",0,0,0,0,1.0,0,2.5,0, ...
    'VariableNames',{'schema_version','step','coupling_iteration','time_s', ...
    'slice_id','s_ref_m','force_x_N','force_y_N','force_z_N'});
writetable(load_table,load_file);
[slice_force,meta] = ancf_read_slice_loads_csv(load_file,model); %#ok<ASGLU>
assert(abs(slice_force(1,2)-2.5) < 1.0e-12);
state_a = ancf_initialize(model);
state_b = ancf_initialize(model);
for k = 1:3
    state_a = ancf_advance_step(state_a,slice_force,model.time.dt);
    state_b = ancf_advance_step(state_b,slice_force,model.time.dt);
end
assert(norm(state_a.q-state_b.q,inf) < 1.0e-12);

% Corrupt slice ID and NaN force must be rejected by the MATLAB reader.
bad = load_table; bad.slice_id = 2; writetable(bad,fullfile(work,'bad_id.csv'));
assert_throws(@() ancf_read_slice_loads_csv(fullfile(work,'bad_id.csv'),model));
bad = load_table; bad.force_y_N = NaN; writetable(bad,fullfile(work,'bad_nan.csv'));
assert_throws(@() ancf_read_slice_loads_csv(fullfile(work,'bad_nan.csv'),model));

fprintf('PASS MATLAB CSV contract: static, sinusoidal, constant-force replay, bad-file rejection.\n');
end

function assert_throws(f)
raised = false;
try
    f();
catch
    raised = true;
end
assert(raised,'Expected the CSV reader to reject the corrupt input.');
end

function cleanup_test_dir(work)
if exist(work,'dir'), rmdir(work,'s'); end
end
