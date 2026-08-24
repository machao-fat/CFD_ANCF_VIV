function M = ancf_mass_matrix(model)
%ANCF_MASS_MATRIX Consistent mass matrix assembled by Gaussian quadrature.
ne = model.geometry.n_elem;
ndof = model.geometry.ndof;
Le = model.geometry.L / ne;
[xi,w] = ancf_gauss_points(5);
rhoA = model.material.rho * model.material.area;
M = zeros(ndof, ndof);

for ie = 1:ne
    Me = zeros(12,12);
    for k = 1:numel(xi)
        x = 0.5*(xi(k)+1)*Le;
        S = ancf_shape(x, Le, 0);
        N = [S(1)*eye(3), S(2)*eye(3), S(3)*eye(3), S(4)*eye(3)];
        Me = Me + w(k) * (N.'*N) * Le/2;
    end
    Me = rhoA * Me;
    istart = 6*(ie-1) + 1;
    M(istart:istart+11, istart:istart+11) = ...
        M(istart:istart+11, istart:istart+11) + Me;
end
M = 0.5*(M+M.');
end
