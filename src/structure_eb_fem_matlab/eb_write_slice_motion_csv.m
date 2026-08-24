function eb_write_slice_motion_csv(motion,filepath)
%EB_WRITE_SLICE_MOTION_CSV Write one complete motion snapshot atomically.
required = {'schema_version','step','coupling_iteration','time_s','slice_id','s_ref_m',...
    'x_m','y_m','z_m','vx_mps','vy_mps','vz_mps','ax_mps2','ay_mps2','az_mps2'};
for k = 1:numel(required)
    if ~isfield(motion,required{k}), error('eb_write_slice_motion_csv:Field','Missing %s.',required{k}); end
end
n = numel(motion.s_ref_m); fields = required(5:end);
for k = 1:numel(fields)
    vals = double(motion.(fields{k})(:));
    if numel(vals) ~= n || any(~isfinite(vals))
        error('eb_write_slice_motion_csv:Finite','Motion field %s is invalid.',fields{k});
    end
end
T = table(repmat(string(motion.schema_version),n,1),repmat(motion.step,n,1),...
    repmat(motion.coupling_iteration,n,1),repmat(motion.time_s,n,1),motion.slice_id(:),motion.s_ref_m(:),...
    motion.x_m(:),motion.y_m(:),motion.z_m(:),motion.vx_mps(:),motion.vy_mps(:),motion.vz_mps(:),...
    motion.ax_mps2(:),motion.ay_mps2(:),motion.az_mps2(:),...
    'VariableNames',{'schema_version','step','coupling_iteration','time_s','slice_id','s_ref_m',...
    'x_m','y_m','z_m','vx_mps','vy_mps','vz_mps','ax_mps2','ay_mps2','az_mps2'});
[folder,~,~] = fileparts(filepath); if isempty(folder), folder = pwd; end
if ~exist(folder,'dir'), mkdir(folder); end
tmp = [tempname(folder),'.csv']; cleanup = onCleanup(@() eb_delete_if_exists(tmp));
writetable(T,tmp); movefile(tmp,filepath,'f'); clear cleanup
end

function eb_delete_if_exists(filepath)
if exist(filepath,'file'), delete(filepath); end
end
