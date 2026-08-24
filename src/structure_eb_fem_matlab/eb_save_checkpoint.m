function eb_save_checkpoint(state,filepath)
%EB_SAVE_CHECKPOINT Save a complete EB state for restart/rollback.
if nargin < 2 || isempty(filepath), error('eb_save_checkpoint:Path','A path is required.'); end
save(filepath,'state','-v7');
end
