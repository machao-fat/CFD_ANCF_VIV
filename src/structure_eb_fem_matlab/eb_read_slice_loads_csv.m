function [slice_force,meta] = eb_read_slice_loads_csv(filepath,model)
%EB_READ_SLICE_LOADS_CSV Read the shared integrated-N slice-load protocol.
if ~exist(filepath,'file'), error('eb_read_slice_loads_csv:Missing','File not found: %s',filepath); end
T = readtable(filepath,'TextType','string');
required = {'schema_version','step','coupling_iteration','time_s','s_ref_m',...
    'force_x_N','force_y_N','force_z_N'};
missing = setdiff(required,T.Properties.VariableNames);
if ~isempty(missing), error('eb_read_slice_loads_csv:Schema','Missing: %s',strjoin(missing,',')); end
ns = numel(model.coupling.s_ref_m);
if height(T) ~= ns, error('eb_read_slice_loads_csv:Rows','Expected %d rows, got %d.',ns,height(T)); end
if ismember('slice_id',T.Properties.VariableNames) && any(double(T.slice_id) ~= (0:ns-1).')
    error('eb_read_slice_loads_csv:SliceId','slice_id must be 0..nSlices-1.');
end
if max(abs(double(T.s_ref_m)-model.coupling.s_ref_m(:))) > 1e-10*max(1,model.geometry.L)
    error('eb_read_slice_loads_csv:ArcLength','s_ref_m mismatch.');
end
numeric_names = {'step','coupling_iteration','time_s','s_ref_m','force_x_N','force_y_N','force_z_N'};
for k = 1:numel(numeric_names)
    if any(~isfinite(double(T.(numeric_names{k})))), error('eb_read_slice_loads_csv:Finite','NaN/Inf in %s.',numeric_names{k}); end
end
if any(double(T.step) ~= double(T.step(1))) || any(double(T.coupling_iteration) ~= double(T.coupling_iteration(1))) || ...
        any(abs(double(T.time_s)-double(T.time_s(1))) > 1e-12*max(1,abs(double(T.time_s(1)))))
    error('eb_read_slice_loads_csv:Metadata','Snapshot metadata is not constant.');
end
slice_force = [double(T.force_x_N),double(T.force_y_N),double(T.force_z_N)];
meta = struct('schema_version',char(T.schema_version(1)),'step',double(T.step(1)),...
    'coupling_iteration',double(T.coupling_iteration(1)),'time_s',double(T.time_s(1)),...
    'force_representation','integrated_N');
end
