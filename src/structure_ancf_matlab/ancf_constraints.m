function [fixed,free,values] = ancf_constraints(model)
%ANCF_CONSTRAINTS Prescribed position DOFs for a guided top-tensioned riser.
ndof = model.geometry.ndof;
fixed_mask = false(ndof,1);
values = zeros(ndof,1);

bottom = 1:3;
fixed_mask(bottom) = model.boundary.bottom_position_fixed;
values(bottom) = model.boundary.bottom_position;

top0 = 6*(model.geometry.n_node-1)+1;
top = top0:top0+2;
fixed_mask(top) = model.boundary.top_position_fixed;
values(top) = model.boundary.top_position;

fixed = find(fixed_mask);
free = find(~fixed_mask);
end
