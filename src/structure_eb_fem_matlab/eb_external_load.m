function Qcfd = eb_external_load(state_or_model,slice_force)
%EB_EXTERNAL_LOAD Map integrated slice forces to EB generalized forces by H^T.
if isfield(state_or_model,'model')
    model = state_or_model.model;
else
    model = state_or_model;
end
ns = numel(model.coupling.s_ref_m);
if nargin < 2 || isempty(slice_force)
    Qcfd = zeros(model.geometry.ndof,1); return;
end
if size(slice_force,1) ~= ns
    error('eb_external_load:Size','Expected %d slice rows, received %d.',ns,size(slice_force,1));
end
if size(slice_force,2) == 2
    slice_force = [slice_force,zeros(ns,1)];
elseif size(slice_force,2) ~= 3
    error('eb_external_load:Components','slice_force must be [Fx,Fy] or [Fx,Fy,Fz].');
end
if any(~isfinite(slice_force(:)))
    error('eb_external_load:Finite','Slice force contains NaN or Inf.');
end
scale = max(1,max(abs(slice_force(:,1:2)),[],'all'));
if any(abs(slice_force(:,3)) > 1.0e-12*scale)
    error('eb_external_load:AxialForce','Euler-Bernoulli comparator has no axial DOF; Fz must be zero.');
end
if strcmpi(model.coupling.force_representation,'line_Npm')
    slice_force = slice_force.*model.mapping.slice_weights_m;
elseif ~strcmpi(model.coupling.force_representation,'integrated_N')
    error('eb_external_load:Representation','Unknown force representation: %s',model.coupling.force_representation);
end
% H is stored in row-major slice order [x1;y1;x2;y2;...].  Do not use
% reshape on the transposed table here: MATLAB column-major ordering would
% group all Fx rows before all Fy rows.
Fxy = zeros(2*ns,1);
Fxy(1:2:end) = slice_force(:,1);
Fxy(2:2:end) = slice_force(:,2);
Qcfd = model.mapping.H.'*Fxy;
end
