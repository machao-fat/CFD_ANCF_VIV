function out = ancf_postprocess(state)
%ANCF_POSTPROCESS Centerline position, curvature, strain and tension.
model = state.model;
sref = model.post.s_ref_m(:);
ne = model.geometry.n_elem;
Le = model.geometry.L/ne;
n = numel(sref);
xyz = zeros(n,3); tangent = zeros(n,3); curvature = zeros(n,3);
strain = zeros(n,1); tension = zeros(n,1);

for k = 1:n
    s = min(max(sref(k),0),model.geometry.L);
    if s == model.geometry.L
        ie = ne; x = Le;
    else
        ie = min(floor(s/Le)+1,ne); x = s-(ie-1)*Le;
    end
    idx = 6*(ie-1)+1:6*(ie-1)+12;
    qe = state.q(idx);
    S0 = ancf_shape(x,Le,0); S1 = ancf_shape(x,Le,1); S2 = ancf_shape(x,Le,2);
    N0 = [S0(1)*eye(3),S0(2)*eye(3),S0(3)*eye(3),S0(4)*eye(3)];
    N1 = [S1(1)*eye(3),S1(2)*eye(3),S1(3)*eye(3),S1(4)*eye(3)];
    N2 = [S2(1)*eye(3),S2(2)*eye(3),S2(3)*eye(3),S2(4)*eye(3)];
    rs = N1*qe; rss = N2*qe; nr = norm(rs);
    xyz(k,:) = (N0*qe).';
    tangent(k,:) = (rs/nr).';
    curvature(k,:) = (cross(rs,rss)/(nr^3)).';
    strain(k) = 0.5*(dot(rs,rs)-1.0);
    % For Green strain, EA*epsilon is the material (second-Piola-like)
    % measure. The current axial force magnitude additionally contains the
    % current tangent stretch ||r_s||.
    tension(k) = model.material.EA*strain(k)*nr;
end

internal_energy = 0.0;
for ie = 1:ne
    idx = 6*(ie-1)+1:6*(ie-1)+12;
    internal_energy = internal_energy + ancf_element_energy(state.q(idx),Le, ...
        model.material.EA,model.material.EI,model.integration.n_gauss);
end
kinetic_energy = 0.5*state.qd.'*model.mass_matrix*state.qd;
external_potential = -state.base_load.'*state.q;

out = struct('s_ref_m',sref,'x_m',xyz(:,1),'y_m',xyz(:,2),'z_m',xyz(:,3), ...
    'tangent',tangent,'curvature_1pm',curvature,'curvature_mag_1pm',vecnorm(curvature,2,2), ...
    'axial_strain',strain,'material_axial_force_N',model.material.EA*strain, ...
    'tension_N',tension,'internal_energy_J',internal_energy, ...
    'kinetic_energy_J',kinetic_energy,'external_potential_J',external_potential, ...
    'mechanical_energy_J',internal_energy+kinetic_energy+external_potential);
end
