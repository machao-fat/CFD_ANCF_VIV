function ancf_save_checkpoint(state,filepath)
%ANCF_SAVE_CHECKPOINT Atomically save a complete structure state.
if nargin < 2 || isempty(filepath)
    error('ancf_save_checkpoint:Path','A checkpoint filepath is required.');
end
required = {'schema_version','model','q','qd','qdd','t','step','last_slice_force_N'};
for k = 1:numel(required)
    if ~isfield(state,required{k})
        error('ancf_save_checkpoint:State','State is missing field %s.',required{k});
    end
end
[folder,~,~] = fileparts(filepath);
if isempty(folder), folder = pwd; end
if ~exist(folder,'dir'), mkdir(folder); end
tmp = [tempname(folder),'.mat'];
cleanup = onCleanup(@() delete_if_exists(tmp));
save(tmp,'state','-v7');
movefile(tmp,filepath,'f');
clear cleanup
end

function delete_if_exists(filepath)
if exist(filepath,'file'), delete(filepath); end
end
