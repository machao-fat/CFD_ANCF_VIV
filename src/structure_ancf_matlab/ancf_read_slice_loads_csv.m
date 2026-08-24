function [slice_force,meta] = ancf_read_slice_loads_csv(filepath,model)
%ANCF_READ_SLICE_LOADS_CSV Read OpenFOAM slice loads in integrated newtons.
if ~exist(filepath,'file')
    error('ancf_read_slice_loads_csv:Missing', 'Load file not found: %s',filepath);
end
T = readtable(filepath,'TextType','string');
required = {'schema_version','step','coupling_iteration','time_s','s_ref_m', ...
    'force_x_N','force_y_N','force_z_N'};
missing = setdiff(required,T.Properties.VariableNames);
if ~isempty(missing)
    error('ancf_read_slice_loads_csv:Schema', 'Missing columns: %s',strjoin(missing,', '));
end
ns = numel(model.coupling.s_ref_m);
if height(T) ~= ns
    error('ancf_read_slice_loads_csv:Rows', 'Expected %d slices, received %d.',ns,height(T));
end
if ismember('slice_id',T.Properties.VariableNames)
    expected_id = (0:ns-1).';
    if any(double(T.slice_id) ~= expected_id)
        error('ancf_read_slice_loads_csv:SliceId', 'slice_id must be contiguous and ordered from 0.');
    end
end
s = double(T.s_ref_m);
if max(abs(s-model.coupling.s_ref_m(:))) > 1.0e-10*max(1,model.geometry.L)
    error('ancf_read_slice_loads_csv:ArcLength', 'Slice reference positions do not match the case.');
end
if any(~isfinite(T.force_x_N)) || any(~isfinite(T.force_y_N)) || any(~isfinite(T.force_z_N))
    error('ancf_read_slice_loads_csv:Finite', 'Slice load contains NaN or Inf.');
end
if any(~isfinite(double(T.step))) || any(~isfinite(double(T.coupling_iteration))) || any(~isfinite(double(T.time_s)))
    error('ancf_read_slice_loads_csv:Finite', 'Load metadata contains NaN or Inf.');
end
if any(double(T.step) ~= double(T.step(1))) || any(double(T.coupling_iteration) ~= double(T.coupling_iteration(1))) || ...
        any(abs(double(T.time_s)-double(T.time_s(1))) > 1.0e-12*max(1,abs(double(T.time_s(1)))))
    error('ancf_read_slice_loads_csv:Metadata', 'Load metadata must be constant across all slices.');
end
slice_force = [double(T.force_x_N),double(T.force_y_N),double(T.force_z_N)];
meta = struct('schema_version',char(T.schema_version(1)),'step',T.step(1), ...
    'coupling_iteration',T.coupling_iteration(1),'time_s',T.time_s(1), ...
    'force_representation','integrated_N');
end
