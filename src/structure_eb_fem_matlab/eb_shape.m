function N = eb_shape(x,L,derivative)
%EB_SHAPE Cubic Hermite shape functions and their x derivatives.
xi = x/L;
switch derivative
    case 0
        N = [1-3*xi^2+2*xi^3; L*(xi-2*xi^2+xi^3);...
            3*xi^2-2*xi^3; L*(-xi^2+xi^3)];
    case 1
        N = [(-6*xi+6*xi^2)/L; 1-4*xi+3*xi^2;...
            (6*xi-6*xi^2)/L; -2*xi+3*xi^2];
    case 2
        N = [(-6+12*xi)/L^2; (-4+6*xi)/L;...
            (6-12*xi)/L^2; (-2+6*xi)/L];
    otherwise
        error('eb_shape:Derivative','Derivative must be 0, 1, or 2.');
end
end
