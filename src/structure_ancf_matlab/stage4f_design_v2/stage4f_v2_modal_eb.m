function modal = stage4f_v2_modal_eb(model,nMode)
%STAGE4F_V2_MODAL_EB One transverse plane, wet consistent mass, guided ends.
if nargin < 2, nMode = 4; end
nNode = model.geometry.n_node;
yDof = reshape([4*(0:nNode-1)+3;4*(0:nNode-1)+4],[],1);
fixed = [3,4*(nNode-1)+3];
free = setdiff(yDof,fixed,'stable');
K = 0.5*(model.matrices.K(free,free)+model.matrices.K(free,free).');
M = 0.5*(model.matrices.M(free,free)+model.matrices.M(free,free).');
[V,D] = eig(K,M,'vector');
keep = isfinite(D) & real(D) > 1e-12 & abs(imag(D)) < 1e-9;
D = real(D(keep)); V = real(V(:,keep));
[D,order] = sort(D); V = V(:,order);
if numel(D) < nMode, error('stage4f_v2_modal_eb:Modes','Fewer than %d positive modes.',nMode); end
D = D(1:nMode); V = V(:,1:nMode);
for k = 1:nMode
    scale = sqrt(V(:,k).'*M*V(:,k));
    V(:,k) = V(:,k)/scale;
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
    N = eb_shape(x,Le,0).';
    nodes = [ie,ie+1];
    ids = [4*(nodes(1)-1)+3,4*(nodes(1)-1)+4,4*(nodes(2)-1)+3,4*(nodes(2)-1)+4];
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
