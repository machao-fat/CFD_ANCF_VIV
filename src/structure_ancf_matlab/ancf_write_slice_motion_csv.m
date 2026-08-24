function ancf_write_slice_motion_csv(motion, filepath)
%ANCF_WRITE_SLICE_MOTION_CSV Write a committed CFD motion request.
required = {'step','coupling_iteration','time_s','slice_id','s_ref_m','x_m','y_m','z_m','vx_mps','vy_mps','vz_mps', ...
    'ax_mps2','ay_mps2','az_mps2'};
for k = 1:numel(required)
    if ~isfield(motion,required{k})
        error('ancf_write_slice_motion_csv:Field', 'Missing motion field %s.',required{k});
    end
end
n = numel(motion.s_ref_m);
data = table(repmat(string(motion.schema_version),n,1), ...
    repmat(motion.step,n,1),repmat(motion.coupling_iteration,n,1),repmat(motion.time_s,n,1),motion.slice_id(:),motion.s_ref_m(:), ...
    motion.x_m(:),motion.y_m(:),motion.z_m(:),motion.vx_mps(:),motion.vy_mps(:),motion.vz_mps(:), ...
    motion.ax_mps2(:),motion.ay_mps2(:),motion.az_mps2(:), ...
    'VariableNames',{'schema_version','step','coupling_iteration','time_s','slice_id','s_ref_m','x_m','y_m','z_m', ...
    'vx_mps','vy_mps','vz_mps','ax_mps2','ay_mps2','az_mps2'});
write_atomic_table(data,filepath);
end

function write_atomic_table(data,filepath)
[folder,~,~] = fileparts(filepath);
if isempty(folder), folder = pwd; end
if ~exist(folder,'dir'), mkdir(folder); end
% Keep a CSV extension because writetable infers the file type from it.
tmp = [tempname(folder),'.csv'];
cleanup = onCleanup(@() delete_if_exists(tmp));
writetable(data,tmp);
movefile(tmp,filepath,'f');
clear cleanup
end

function delete_if_exists(filepath)
if exist(filepath,'file'), delete(filepath); end
end
