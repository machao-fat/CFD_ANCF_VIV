function T = eb_pretension_profile(model,s,mode)
%EB_PRETENSION_PROFILE Return the frozen axial tension used by the EB model.
% s is measured from the ANCF bottom reference point toward the top.
if nargin < 3 || isempty(mode)
    mode = model.pretension.mode;
end
switch lower(char(mode))
    case 'ancf_initial_balance'
        wsub = model.pretension.ancf_initial_weight_Npm;
        % The same vertical body load used by ancf_base_load: T'=wsub,
        % T(L)=Ttop, hence T(s)=Ttop-wsub*(L-s).
    case 'paper_formula'
        wsub = model.pretension.paper_unit_weight_Npm;
    otherwise
        error('eb_pretension_profile:Mode','Unknown pretension mode: %s',char(mode));
end
T = model.pretension.top_tension_N - wsub.*(model.geometry.L-s);
end
