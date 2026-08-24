function Q = eb_consistent_load(model,line_load_Npm)
%EB_CONSISTENT_LOAD Assemble consistent nodal loads for [Fx,Fy] per length.
if nargin < 2 || isempty(line_load_Npm)
    line_load_Npm = [0;0];
end
line_load_Npm = line_load_Npm(:);
if numel(line_load_Npm) ~= 2 || any(~isfinite(line_load_Npm))
    error('eb_consistent_load:Input','line_load_Npm must contain finite [Fx;Fy].');
end
ne = model.geometry.n_elem; Le = model.geometry.L/ne;
[xi,w] = eb_gauss_points(model.integration.n_gauss);
Q = zeros(model.geometry.ndof,1);
for ie = 1:ne
    fe_x = zeros(4,1);
    fe_y = zeros(4,1);
    for k = 1:numel(xi)
        x = 0.5*(xi(k)+1)*Le;
        N = eb_shape(x,Le,0);
        fe_x = fe_x + N*line_load_Npm(1)*w(k)*Le/2;
        fe_y = fe_y + N*line_load_Npm(2)*w(k)*Le/2;
    end
    nodes = [ie,ie+1];
    ids_x = [4*(nodes(1)-1)+1,4*(nodes(1)-1)+2,4*(nodes(2)-1)+1,4*(nodes(2)-1)+2];
    ids_y = ids_x+2;
    Q(ids_x) = Q(ids_x)+fe_x;
    Q(ids_y) = Q(ids_y)+fe_y;
end
end
