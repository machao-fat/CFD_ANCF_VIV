function U = ancf_element_energy(qe, Le, EA, EI, ngauss)
%ANCF_ELEMENT_ENERGY Green-strain/bending energy of one ANCF beam element.
[xi,w] = ancf_gauss_points(ngauss);
U = 0.0;
for k = 1:numel(xi)
    x = 0.5*(xi(k)+1)*Le;
    Sx = ancf_shape(x, Le, 1);
    Sxx = ancf_shape(x, Le, 2);
    B = [Sx(1)*eye(3), Sx(2)*eye(3), Sx(3)*eye(3), Sx(4)*eye(3)];
    B2 = [Sxx(1)*eye(3), Sxx(2)*eye(3), Sxx(3)*eye(3), Sxx(4)*eye(3)];
    rs = B*qe;
    rss = B2*qe;
    nr = norm(rs);
    if nr < 1.0e-12
        error('ancf_element_energy:Degenerate', 'Centerline tangent is nearly zero.');
    end
    eps = 0.5*(dot(rs,rs)-1.0);
    curvature = cross(rs,rss)/(nr^3);
    U = U + w(k) * (0.5*EA*eps^2 + 0.5*EI*dot(curvature,curvature)) * Le/2;
end
end
