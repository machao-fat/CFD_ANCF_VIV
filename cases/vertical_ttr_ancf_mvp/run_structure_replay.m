function state = run_structure_replay(output_dir)
%RUN_STRUCTURE_REPLAY Run a short structure-master load-replay example.
% This is not an OpenFOAM solver. It demonstrates the exact structure-side
% clock and file hand-off that the future OpenFOAM adapter will replace.
if nargin < 1 || isempty(output_dir)
    output_dir = fullfile(pwd,'coupling_output');
end
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(root,'src','structure_ancf_matlab'));

model = vertical_ttr_case('L',20,'D',0.028,'dInner',0.024,'nElem',4, ...
    'nSlices',5,'topTension_N',1000,'dt',1.0e-3);
state = ancf_initialize(model);
if ~exist(output_dir,'dir'), mkdir(output_dir); end

nstep = 20;
for k = 1:nstep
    t = state.t + model.time.dt;
    slice_force = zeros(numel(model.coupling.s_ref_m),3);
    slice_force(:,2) = 0.2*sin(2*pi*0.5*t);
    state = ancf_advance_step(state,slice_force,model.time.dt);
    motion = ancf_slice_motion(state);
    filename = fullfile(output_dir,sprintf('slice_motion_%08d.csv',state.step));
    ancf_write_slice_motion_csv(motion,filename);
end
end
