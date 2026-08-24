function [Qbody,Qtop,Qbase] = ancf_base_load(model)
%ANCF_BASE_LOAD Assemble gravity/buoyancy and top axial force.
ne = model.geometry.n_elem;
ndof = model.geometry.ndof;
Le = model.geometry.L/ne;
[xi,w] = ancf_gauss_points(model.integration.n_gauss);
Qbody = zeros(ndof,1);

line_force = zeros(3,1);
if model.physics.include_gravity
    line_force(3) = line_force(3) - model.material.rho*model.material.area*model.fluid.g;
end
if model.physics.include_buoyancy
    line_force(3) = line_force(3) + model.fluid.rho*model.material.area_displaced*model.fluid.g;
end

for ie = 1:ne
    istart = 6*(ie-1)+1;
    Qe = zeros(12,1);
    for k = 1:numel(xi)
        x = 0.5*(xi(k)+1)*Le;
        S = ancf_shape(x,Le,0);
        N = [S(1)*eye(3), S(2)*eye(3), S(3)*eye(3), S(4)*eye(3)];
        Qe = Qe + w(k)*N.'*line_force*Le/2;
    end
    Qbody(istart:istart+11) = Qbody(istart:istart+11) + Qe;
end

Qtop = zeros(ndof,1);
top0 = 6*(model.geometry.n_node-1)+1;
Qtop(top0:top0+2) = [0;0;model.boundary.top_tension_N];
Qbase = Qbody + Qtop;
end
