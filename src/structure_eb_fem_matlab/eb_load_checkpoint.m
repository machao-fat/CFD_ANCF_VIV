function state = eb_load_checkpoint(filepath)
%EB_LOAD_CHECKPOINT Load and validate an EB checkpoint.
if ~exist(filepath,'file'), error('eb_load_checkpoint:Missing','File not found: %s',filepath); end
data = load(filepath,'state');
if ~isfield(data,'state') || ~isfield(data.state,'model') || ~isfield(data.state,'q')
    error('eb_load_checkpoint:Schema','Invalid EB checkpoint.');
end
state = data.state;
end
