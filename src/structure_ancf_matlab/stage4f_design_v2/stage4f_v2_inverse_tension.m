function [T,audit] = stage4f_v2_inverse_tension(c,mass_ratio,beta)
%STAGE4F_V2_INVERSE_TENSION Root the actual nElem=32 EB wet eigenfrequency.
m_eff = (mass_ratio+c.Ca)*c.m_f;
Tstring = (2*c.L*c.f_target)^2*m_eff/(1+beta*pi^2);
wsub = (mass_ratio*c.m_f-c.m_f)*c.g;
lower = max(1.0,0.01*wsub*c.L);
upper = max([1e5,10*Tstring,2*wsub*c.L]);
bracket = [];
for iextend = 1:5
    grid = logspace(log10(lower),log10(upper),160);
    values = NaN(size(grid));
    for k = 1:numel(grid)
        values(k) = frequency_error(grid(k));
    end
    for k = 1:numel(grid)-1
        if isfinite(values(k)) && isfinite(values(k+1)) && values(k)*values(k+1) <= 0
            bracket = [grid(k),grid(k+1)]; %#ok<AGROW>
            break;
        end
    end
    if ~isempty(bracket), break; end
    upper = upper*10;
end
if isempty(bracket)
    error('stage4f_v2_inverse_tension:Bracket', ...
        'No positive-definite EB bracket for m*=%.0f beta=%.3g.',mass_ratio,beta);
end
options = optimset('TolX',1e-9,'Display','off');
T = fzero(@frequency_error,bracket,options);
model = stage4f_v2_build_eb(c,mass_ratio,beta,T,32,9);
modal = stage4f_v2_modal_eb(model,4);
audit.method = 'fzero_actual_EB_FEM_nElem32';
audit.string_theory_initial_T_N = Tstring;
audit.root_bracket_N = bracket;
audit.top_tension_N = T;
audit.final_frequency_Hz = modal.frequency_Hz(1);
audit.target_frequency_Hz = c.f_target;
audit.relative_frequency_error = abs(modal.frequency_Hz(1)-c.f_target)/c.f_target;
audit.function_evaluations_finite = true;

    function value = frequency_error(trialT)
        try
            trial = stage4f_v2_build_eb(c,mass_ratio,beta,trialT,32,9);
            nNode = trial.geometry.n_node;
            yDof = reshape([4*(0:nNode-1)+3;4*(0:nNode-1)+4],[],1);
            free = setdiff(yDof,[3,4*(nNode-1)+3],'stable');
            K = 0.5*(trial.matrices.K(free,free)+trial.matrices.K(free,free).');
            [~,flag] = chol(K);
            if flag ~= 0, value=NaN; return; end
            one = stage4f_v2_modal_eb(trial,1);
            value = one.frequency_Hz(1)-c.f_target;
        catch
            value = NaN;
        end
    end
end

