function [Q,K] = ancf_internal_force_tangent(q, model)
%ANCF_INTERNAL_FORCE_TANGENT Analytic ANCF internal force and tangent.
%
% The element energy is
%   U = 1/2*EA*epsilon^2 + 1/2*EI*||cross(r_s,r_ss)||^2/||r_s||^6.
% The returned tangent is assembled from the exact derivatives with respect
% to r_s and r_ss. This replaces the first-MVP energy finite difference and
% leaves the public structure/CFD interface unchanged.

ne = model.geometry.n_elem;
ndof = model.geometry.ndof;
Le = model.geometry.L / ne;
EA = model.material.EA;
EI = model.material.EI;
Q = zeros(ndof,1);
K = zeros(ndof,ndof);

for ie = 1:ne
    istart = 6*(ie-1)+1;
    idx = istart:istart+11;
    qe = q(idx);
    [fe,Ke] = element_analytic(qe,Le,EA,EI,model.integration.n_gauss);
    Q(idx) = Q(idx) + fe;
    K(idx,idx) = K(idx,idx) + Ke;
end

if model.numerics.symmetrize_tangent
    K = 0.5*(K+K.');
end
end

function [fe,Ke] = element_analytic(qe,Le,EA,EI,ngauss)
[xi,w] = ancf_gauss_points(ngauss);
fe = zeros(12,1);
Ke = zeros(12,12);
I3 = eye(3);

for k = 1:numel(xi)
    x = 0.5*(xi(k)+1)*Le;
    S1 = ancf_shape(x,Le,1);
    S2 = ancf_shape(x,Le,2);
    B = [S1(1)*I3,S1(2)*I3,S1(3)*I3,S1(4)*I3];
    C = [S2(1)*I3,S2(2)*I3,S2(3)*I3,S2(4)*I3];

    a = B*qe;
    b = C*qe;
    a2 = dot(a,a);
    if a2 < 1.0e-24
        error('ancf_internal_force_tangent:Degenerate', ...
            'Centerline tangent is nearly zero.');
    end
    v = cross(a,b);
    v2 = dot(v,v);
    Xa = cross_matrix(a);
    Xb = cross_matrix(b);
    Xv = cross_matrix(v);

    eps = 0.5*(a2-1.0);
    % Derivatives of bending energy with respect to a=r_s and b=r_ss.
    ga_b = a2^(-3)*(Xb*v) - 3*v2*a2^(-4)*a;
    gb_b = -a2^(-3)*(Xa*v);

    Haa_b = -a2^(-3)*(Xb*Xb) ...
        - 6*a2^(-4)*(Xb*v)*a.' ...
        - 3*a2^(-4)*a*(Xb*v).' ...
        + 24*v2*a2^(-5)*(a*a.') ...
        - 3*v2*a2^(-4)*I3;
    Hab_b = a2^(-3)*(-Xv + Xb*Xa) + 3*a2^(-4)*a*(Xa*v).';
    Hbb_b = -a2^(-3)*(Xa*Xa);

    ga = EA*eps*a + EI*ga_b;
    gb = EI*gb_b;
    Haa = EA*(a*a.' + eps*I3) + EI*Haa_b;
    Hab = EI*Hab_b;
    Hbb = EI*Hbb_b;

    fe = fe + (B.'*ga + C.'*gb) * w(k)*Le/2;
    Ke = Ke + (B.'*Haa*B + B.'*Hab*C + C.'*Hab.'*B + C.'*Hbb*C) * w(k)*Le/2;
end
end

function X = cross_matrix(a)
%X maps b to cross(a,b).
X = [0, -a(3), a(2); a(3), 0, -a(1); -a(2), a(1), 0];
end
