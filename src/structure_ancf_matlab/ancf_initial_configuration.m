function q0 = ancf_initial_configuration(model)
%ANCF_INITIAL_CONFIGURATION Straight vertical reference configuration.
ne = model.geometry.n_elem;
q0 = zeros(model.geometry.ndof,1);
r0 = model.boundary.bottom_position;
r1 = model.boundary.top_position;
tangent = (r1-r0)/model.geometry.L;
for inode = 0:ne
    s = inode*model.geometry.L/ne;
    base = 6*inode+1;
    q0(base:base+2) = r0 + tangent*s;
    q0(base+3:base+5) = tangent;
end
end
