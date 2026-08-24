function out = eb_postprocess(state)
%EB_POSTPROCESS Transverse response, energies, and frozen T0 audit fields.
model = state.model; sref = model.post.s_ref_m(:); n = numel(sref);
ne = model.geometry.n_elem; Le = model.geometry.L/ne;
xy = zeros(n,2); slopes = zeros(n,2); curv = zeros(n,2);
for k = 1:n
    s = min(max(sref(k),0),model.geometry.L);
    if s == model.geometry.L, ie = ne; x = Le;
    else, ie = min(floor(s/Le)+1,ne); x = s-(ie-1)*Le; end
    N0 = eb_shape(x,Le,0).'; N1 = eb_shape(x,Le,1).'; N2 = eb_shape(x,Le,2).';
    nodes = [ie,ie+1];
    ids_x = [4*(nodes(1)-1)+1,4*(nodes(1)-1)+2,4*(nodes(2)-1)+1,4*(nodes(2)-1)+2];
    ids_y = ids_x+2;
    xy(k,:) = [N0*state.q(ids_x),N0*state.q(ids_y)];
    slopes(k,:) = [N1*state.q(ids_x),N1*state.q(ids_y)];
    curv(k,:) = [N2*state.q(ids_x),N2*state.q(ids_y)];
end
T0 = eb_pretension_profile(model,sref);
kinetic = 0.5*state.qd.'*model.matrices.M*state.qd;
bending = 0.5*state.q.'*model.matrices.K_bending*state.q;
axial = 0.5*state.q.'*model.matrices.K_geometric*state.q;
external_potential = -state.base_load.'*state.q;
out = struct('s_ref_m',sref,'x_m',xy(:,1),'y_m',xy(:,2),'z_m',sref,...
    'slope_x',slopes(:,1),'slope_y',slopes(:,2),...
    'curvature_x_1pm',curv(:,1),'curvature_y_1pm',curv(:,2),...
    'curvature_mag_1pm',sqrt(sum(curv.^2,2)),...
    'tension_profile_N',T0,'min_tension_N',min(T0),'max_tension_N',max(T0),...
    'compression_risk',any(T0 < 0),'kinetic_energy_J',kinetic,...
    'bending_energy_J',bending,'axial_strain_energy_J',axial,...
    'pre_tension_geometric_energy_J',axial,'external_potential_J',external_potential,...
    'mechanical_energy_J',kinetic+bending+axial+external_potential);
end
