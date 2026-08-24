function modal = eb_modal_analysis(model,nMode)
%EB_MODAL_ANALYSIS Solve the constrained generalized eigenproblem.
if nargin < 2 || isempty(nMode), nMode = 6; end
if ~isfield(model,'matrices'), model.matrices = eb_build_matrices(model); end
[~,free,~] = eb_constraints(model);
Kff = 0.5*(model.matrices.K(free,free)+model.matrices.K(free,free).');
Mff = 0.5*(model.matrices.M(free,free)+model.matrices.M(free,free).');
[V,D] = eig(Kff,Mff);
lambda = real(diag(D));
keep = isfinite(lambda) & lambda > 1e-10;
lambda = lambda(keep); V = V(:,keep);
[lambda,order] = sort(lambda); V = V(:,order);
nMode = min(nMode,numel(lambda));
modal = struct('lambda_rad2ps2',lambda(1:nMode),...
    'frequency_Hz',sqrt(lambda(1:nMode))/(2*pi),...
    'mode_shape_free',V(:,1:nMode),'free_dof',free);
end
