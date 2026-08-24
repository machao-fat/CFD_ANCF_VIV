function Q = eb_point_load(model,s,force_xy_N)
%EB_POINT_LOAD Consistent generalized load for a transverse point force.
% The load is applied at reference arc length s and is mapped with the same
% Hermite interpolation operator used by the CFD H/H^T interface.
if nargin < 3 || numel(force_xy_N) ~= 2 || any(~isfinite(force_xy_N(:)))
    error('eb_point_load:Input','force_xy_N must be finite [Fx;Fy].');
end
if ~(isscalar(s) && isfinite(s) && s >= 0 && s <= model.geometry.L)
    error('eb_point_load:ArcLength','s must lie in [0,L].');
end

ne = model.geometry.n_elem;
Le = model.geometry.L/ne;
if s == model.geometry.L
    ie = ne; x = Le;
else
    ie = min(floor(s/Le)+1,ne);
    x = s-(ie-1)*Le;
end
N = eb_shape(x,Le,0);
nodes = [ie,ie+1];
ids_x = [4*(nodes(1)-1)+1,4*(nodes(1)-1)+2,4*(nodes(2)-1)+1,4*(nodes(2)-1)+2];
ids_y = ids_x + 2;
Q = zeros(model.geometry.ndof,1);
Q(ids_x) = Q(ids_x) + N*force_xy_N(1);
Q(ids_y) = Q(ids_y) + N*force_xy_N(2);
end
