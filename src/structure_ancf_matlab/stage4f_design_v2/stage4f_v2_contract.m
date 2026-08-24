function c = stage4f_v2_contract()
%STAGE4F_V2_CONTRACT Frozen SI inputs for the corrected low-Re benchmark.
c.schema_version = 'stage4f-a-v2-matlab-1.0';
c.D = 1.0;
c.di = 0.9;
c.L = 50.0;
c.U = 1.0;
c.rho_f = 1000.0;
c.nu = 0.01;
c.g = 9.81;
c.Ca = 1.0;
c.zeta = 0.01;
c.Ur1 = 5.5;
c.f_target = c.U/(c.Ur1*c.D);
c.A = pi*(c.D^2-c.di^2)/4;
c.I = pi*(c.D^4-c.di^4)/64;
c.area_displaced = pi*c.D^2/4;
c.m_f = c.rho_f*c.area_displaced;
c.m_added = c.Ca*c.m_f;
c.mass_ratios = [2,5,10];
c.betas = [0.01,0.05];
c.n_elem = [8,16,32];
c.St = [0.15,0.18];
c.Cl_amp = [0.1,0.3];
c.runtime_dir = fullfile(pwd,'runtime','stage4f_lowre_benchmark_design_v2');
c.result_dir = fullfile(pwd,'results','11_stage4f_lowre_benchmark_design_v2');
end

