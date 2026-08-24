function Qcfd = ancf_external_load(state_or_model, slice_force)
%ANCF_EXTERNAL_LOAD Map slice forces to ANCF generalized forces with H^T.
if isfield(state_or_model,'model')
    model = state_or_model.model;
else
    model = state_or_model;
end
ns = numel(model.coupling.s_ref_m);
if nargin < 2 || isempty(slice_force)
    Qcfd = zeros(model.geometry.ndof,1);
    return;
end

if size(slice_force,1) ~= ns
    error('ancf_external_load:Size', 'Expected %d slice rows, received %d.',ns,size(slice_force,1));
end
if size(slice_force,2) == 2
    slice_force = [slice_force, zeros(ns,1)];
elseif size(slice_force,2) ~= 3
    error('ancf_external_load:Components', 'slice_force must have 2 or 3 columns [Fx,Fy,(Fz)].');
end

if any(~isfinite(slice_force(:)))
    error('ancf_external_load:Finite', 'Slice force contains NaN or Inf.');
end

if strcmpi(model.coupling.force_representation,'line_Npm')
    slice_force = slice_force .* model.mapping.slice_weights_m;
elseif ~strcmpi(model.coupling.force_representation,'integrated_N')
    error('ancf_external_load:Representation', 'Unknown force representation: %s',model.coupling.force_representation);
end

% H3 is stored in row-major slice order [x1;y1;z1;x2;y2;z2;...].
% MATLAB's column-major reshape would silently group components by direction
% and apply force i to slice j.  Build the protocol ordering explicitly.
F = zeros(3*ns,1);
F(1:3:end) = slice_force(:,1);
F(2:3:end) = slice_force(:,2);
F(3:3:end) = slice_force(:,3);
Qcfd = model.mapping.H3.' * F;
end
