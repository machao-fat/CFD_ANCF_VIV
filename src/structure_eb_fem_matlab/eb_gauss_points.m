function [x,w] = eb_gauss_points(n)
%EB_GAUSS_POINTS Gauss-Legendre points and weights on [-1,1].
switch n
    case 1
        x = 0; w = 2;
    case 2
        x = [-1;1]/sqrt(3); w = [1;1];
    case 3
        x = [-sqrt(3/5);0;sqrt(3/5)]; w = [5/9;8/9;5/9];
    case 4
        x = [-sqrt((3+2*sqrt(6/5))/7);-sqrt((3-2*sqrt(6/5))/7);...
            sqrt((3-2*sqrt(6/5))/7);sqrt((3+2*sqrt(6/5))/7)];
        w = [(18-sqrt(30))/36;(18+sqrt(30))/36;...
            (18+sqrt(30))/36;(18-sqrt(30))/36];
    case 5
        x = [-sqrt(5+2*sqrt(10/7))/3;-sqrt(5-2*sqrt(10/7))/3;0;...
            sqrt(5-2*sqrt(10/7))/3;sqrt(5+2*sqrt(10/7))/3];
        w = [(322-13*sqrt(70))/900;(322+13*sqrt(70))/900;128/225;...
            (322+13*sqrt(70))/900;(322-13*sqrt(70))/900];
    otherwise
        error('eb_gauss_points:Order','Only 1 through 5 point rules are implemented.');
end
x = x(:); w = w(:);
end
