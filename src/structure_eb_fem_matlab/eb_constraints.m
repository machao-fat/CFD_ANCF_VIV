function [fixed,free,values] = eb_constraints(model)
%EB_CONSTRAINTS Fix end positions in both transverse planes; leave slopes free.
ndof = model.geometry.ndof;
mask = false(ndof,1);
values = zeros(ndof,1);
bottom = 1:4;
mask(bottom([1,3])) = model.boundary.bottom_position_fixed;
values(bottom([1,3])) = model.boundary.bottom_position_xy;
top0 = 4*(model.geometry.n_node-1)+1;
top = top0:top0+3;
mask(top([1,3])) = model.boundary.top_position_fixed;
values(top([1,3])) = model.boundary.top_position_xy;
fixed = find(mask);
free = find(~mask);
end
