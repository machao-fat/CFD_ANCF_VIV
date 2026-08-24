function mapping = ancf_build_mapping(model)
%ANCF_BUILD_MAPPING Build H3 and H2 motion operators for CFD slices.
% H3 maps structure DOFs to [x,y,z] of each slice in row-major slice order.

L = model.geometry.L;
ne = model.geometry.n_elem;
ns = numel(model.coupling.s_ref_m);
Le = L / ne;
H3 = zeros(3*ns, model.geometry.ndof);

for k = 1:ns
    s = min(max(model.coupling.s_ref_m(k), 0), L);
    if s == L
        ie = ne;
        x = Le;
    else
        ie = min(floor(s/Le) + 1, ne);
        x = s - (ie-1)*Le;
    end
    S = ancf_shape(x, Le, 0);
    N = [S(1)*eye(3), S(2)*eye(3), S(3)*eye(3), S(4)*eye(3)];
    istart = 6*(ie-1) + 1;
    H3(3*k-2:3*k, istart:istart+11) = N;
end

H2 = zeros(2*ns, model.geometry.ndof);
for k = 1:ns
    H2(2*k-1:2*k,:) = H3([3*k-2, 3*k-1],:);
end

weights = zeros(ns,1);
if ns == 1
    weights(1) = L;
else
    weights(1) = 0.5*(model.coupling.s_ref_m(2)-model.coupling.s_ref_m(1));
    weights(end) = 0.5*(model.coupling.s_ref_m(end)-model.coupling.s_ref_m(end-1));
    for k = 2:ns-1
        weights(k) = 0.5*(model.coupling.s_ref_m(k+1)-model.coupling.s_ref_m(k-1));
    end
end

mapping = struct('H3', H3, 'H2', H2, 'slice_weights_m', weights, ...
                 's_ref_m', model.coupling.s_ref_m(:));
end
