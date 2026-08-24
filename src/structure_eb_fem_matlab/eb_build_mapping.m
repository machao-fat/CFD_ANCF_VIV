function mapping = eb_build_mapping(model)
%EB_BUILD_MAPPING Build H and H^T position/force maps for two planes.
L = model.geometry.L;
ne = model.geometry.n_elem;
ns = numel(model.coupling.s_ref_m);
Le = L/ne;
H = zeros(2*ns,model.geometry.ndof);
for k = 1:ns
    s = min(max(model.coupling.s_ref_m(k),0),L);
    if s == L
        ie = ne; x = Le;
    else
        ie = min(floor(s/Le)+1,ne); x = s-(ie-1)*Le;
    end
    N = eb_shape(x,Le,0).';
    nodes = [ie,ie+1];
    ids_x = [4*(nodes(1)-1)+1,4*(nodes(1)-1)+2,4*(nodes(2)-1)+1,4*(nodes(2)-1)+2];
    ids_y = ids_x+2;
    H(2*k-1,ids_x) = N;
    H(2*k,ids_y) = N;
end

weights = zeros(ns,1);
if ns == 1
    weights(1) = L;
else
    s = model.coupling.s_ref_m(:);
    weights(1) = 0.5*(s(2)-s(1));
    weights(end) = 0.5*(s(end)-s(end-1));
    for k = 2:ns-1
        weights(k) = 0.5*(s(k+1)-s(k-1));
    end
end
mapping = struct('H',H,'slice_weights_m',weights,'s_ref_m',model.coupling.s_ref_m(:));
end
