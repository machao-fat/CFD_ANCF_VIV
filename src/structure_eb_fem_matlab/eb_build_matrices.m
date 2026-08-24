function matrices = eb_build_matrices(model)
%EB_BUILD_MATRICES Assemble consistent mass, bending, and geometric stiffness.
ne = model.geometry.n_elem;
ndof = model.geometry.ndof;
Le = model.geometry.L/ne;
[xi,w] = eb_gauss_points(model.integration.n_gauss);
M = zeros(ndof,ndof);
Kb = zeros(ndof,ndof);
Kg = zeros(ndof,ndof);

for ie = 1:ne
    Me = zeros(4,4);
    Kbe = zeros(4,4);
    Kge = zeros(4,4);
    s0 = (ie-1)*Le;
    for k = 1:numel(xi)
        x = 0.5*(xi(k)+1)*Le;
        N0 = eb_shape(x,Le,0);
        N1 = eb_shape(x,Le,1);
        N2 = eb_shape(x,Le,2);
        wt = w(k)*Le/2;
        Me = Me + model.material.mass_per_length*(N0*N0.')*wt;
        Kbe = Kbe + model.material.EI*(N2*N2.')*wt;
        T0 = eb_pretension_profile(model,s0+x);
        Kge = Kge + T0*(N1*N1.')*wt;
    end
    nodes = [ie,ie+1];
    ids_x = [4*(nodes(1)-1)+1,4*(nodes(1)-1)+2,4*(nodes(2)-1)+1,4*(nodes(2)-1)+2];
    ids_y = ids_x + 2;
    M(ids_x,ids_x) = M(ids_x,ids_x)+Me;
    M(ids_y,ids_y) = M(ids_y,ids_y)+Me;
    Kb(ids_x,ids_x) = Kb(ids_x,ids_x)+Kbe;
    Kb(ids_y,ids_y) = Kb(ids_y,ids_y)+Kbe;
    Kg(ids_x,ids_x) = Kg(ids_x,ids_x)+Kge;
    Kg(ids_y,ids_y) = Kg(ids_y,ids_y)+Kge;
end

if model.numerics.symmetrize
    M = 0.5*(M+M.'); Kb = 0.5*(Kb+Kb.'); Kg = 0.5*(Kg+Kg.');
end
K = Kb+Kg;
C = model.damping.rayleigh_alpha*M + model.damping.rayleigh_beta*K;
matrices = struct('M',M,'K_bending',Kb,'K_geometric',Kg,'K',K,'C',C, ...
    'T0_bottom_N',eb_pretension_profile(model,0), ...
    'T0_top_N',eb_pretension_profile(model,model.geometry.L));
end
