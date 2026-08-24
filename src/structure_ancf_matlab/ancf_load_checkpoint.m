function state = ancf_load_checkpoint(filepath)
%ANCF_LOAD_CHECKPOINT Load and validate an ANCF structure checkpoint.
if nargin < 1 || ~exist(filepath,'file')
    error('ancf_load_checkpoint:Missing','Checkpoint file not found.');
end
S = load(filepath,'state');
if ~isfield(S,'state') || ~isstruct(S.state)
    error('ancf_load_checkpoint:Schema','Checkpoint does not contain a state struct.');
end
state = S.state;
required = {'schema_version','model','q','qd','qdd','t','step','last_slice_force_N'};
for k = 1:numel(required)
    if ~isfield(state,required{k})
        error('ancf_load_checkpoint:Schema','Checkpoint is missing field %s.',required{k});
    end
end
if ~isscalar(state.t) || ~isscalar(state.step) || ~isfinite(state.t) || ~isfinite(state.step)
    error('ancf_load_checkpoint:State','Checkpoint time or step is invalid.');
end
if any(~isfinite(state.q)) || any(~isfinite(state.qd)) || any(~isfinite(state.qdd))
    error('ancf_load_checkpoint:State','Checkpoint contains non-finite generalized state.');
end
end
