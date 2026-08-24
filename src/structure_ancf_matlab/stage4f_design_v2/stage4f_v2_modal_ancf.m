function modal = stage4f_v2_modal_ancf(state,Mwet,nMode)
%STAGE4F_V2_MODAL_ANCF Linearized transverse wet modes about static balance.
if nargin < 3, nMode = 4; end
model = state.model;
[~,Kfull] = ancf_internal_force_tangent(state.q,model);
nNode = model.geometry.n_node;
yDof = reshape([6*(0:nNode-1)+2;6*(0:nNode-1)+5],[],1);
fixed = [2,6*(nNode-1)+2];
free = setdiff(yDof,fixed,'stable');
K = 0.5*(Kfull(free,free)+Kfull(free,free).');
M = 0.5*(Mwet(free,free)+Mwet(free,free).');
[V,D] = eig(K,M,'vector');
keep = isfinite(D) & real(D) > 1e-12 & abs(imag(D)) < 1e-9;
D = real(D(keep)); V = real(V(:,keep));
[D,order] = sort(D); V = V(:,order);
if numel(D) < nMode, error('stage4f_v2_modal_ancf:Modes','Fewer than %d positive modes.',nMode); end
D = D(1:nMode); V = V(:,1:nMode);
for k = 1:nMode
    V(:,k) = V(:,k)/sqrt(V(:,k).'*M*V(:,k));
end
orth = V.'*M*V-eye(nMode);
residual = zeros(nMode,1);
for k = 1:nMode
    residual(k) = norm(K*V(:,k)-D(k)*M*V(:,k))/(norm(K*V(:,k))+abs(D(k))*norm(M*V(:,k))+eps);
end
fullV = zeros(model.geometry.ndof,nMode); fullV(free,:) = V;
s = linspace(0,model.geometry.L,501).';
shape = zeros(numel(s),nMode);
Le = model.geometry.L/model.geometry.n_elem;
for is = 1:numel(s)
    ss = s(is);
    if ss == model.geometry.L, ie=model.geometry.n_elem; x=Le;
    else, ie=min(floor(ss/Le)+1,model.geometry.n_elem); x=ss-(ie-1)*Le; end
    N = ancf_shape(x,Le,0).';
    nodes = [ie,ie+1];
    ids = [6*(nodes(1)-1)+2,6*(nodes(1)-1)+5,6*(nodes(2)-1)+2,6*(nodes(2)-1)+5];
    shape(is,:) = N*fullV(ids,:);
end
sampleScale = zeros(nMode,1);
for k = 1:nMode
    [~,imax] = max(abs(shape(:,k)));
    sampleScale(k) = abs(shape(imax,k));
    shape(:,k) = shape(:,k)/shape(imax,k);
end
modal.frequency_Hz = sqrt(D)/(2*pi);
modal.lambda_rad2ps2 = D;
modal.mass_orthogonality_inf = norm(orth,inf);
modal.eigen_residual = residual;
modal.stiffness_condition_number = cond(K);
modal.mass_condition_number = cond(M);
modal.sample_s_m = s;
modal.mode_shape = shape;
modal.maximum_sample_displacement_per_mass_normalized_coordinate = sampleScale;
modal.mode_shape_full = fullV;
modal.free_dof = free;
modal.M_free = M;
modal.K_free = K;
end
