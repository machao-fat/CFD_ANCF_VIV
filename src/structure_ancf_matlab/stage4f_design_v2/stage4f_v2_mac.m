function values = stage4f_v2_mac(shapeA,shapeB)
%STAGE4F_V2_MAC Sign-invariant sampled modal assurance criterion.
nMode = min(size(shapeA,2),size(shapeB,2));
values = zeros(nMode,1);
for k = 1:nMode
    a = shapeA(:,k); b = shapeB(:,k);
    values(k) = abs(a.'*b)^2/((a.'*a)*(b.'*b)+eps);
end
end

