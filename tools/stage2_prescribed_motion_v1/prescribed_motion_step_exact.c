/* Fluent CG-motion UDF with a backward step-average velocity.  Fluent calls
   DEFINE_CG_MOTION at t = n*dt while advancing the mesh from (n-1)*dt to
   n*dt, so this telescopes exactly to y(t) at time-step endpoints. */
#include "udf.h"
#include <math.h>
#include <stdio.h>

#define STAGE2_AMPLITUDE 0.10
#define STAGE2_FREQUENCY 0.16
#define STAGE2_OMEGA (6.2831853071795864769 * STAGE2_FREQUENCY)

static real stage2_y(real t)
{
    return STAGE2_AMPLITUDE * sin(STAGE2_OMEGA * t);
}

DEFINE_CG_MOTION(stage2_cylinder_motion_step_exact, dt, vel, omega, time, dtime)
{
    static FILE *audit = NULL;
    static real last_time = -1.0;
    real y0 = stage2_y(time - dtime);
    real y1 = stage2_y(time);
    real vy = STAGE2_AMPLITUDE * STAGE2_OMEGA * cos(STAGE2_OMEGA * time);

    (void)dt;
    if (dtime > 1.0e-14)
        vy = (y1 - y0) / dtime;

    NV_S(vel, =, 0.0);
    NV_S(omega, =, 0.0);
    vel[1] = vy;

#if !RP_NODE
    if (audit == NULL) {
        audit = fopen("stage2_fluent_motion_step_exact_audit.csv", "w");
        if (audit != NULL)
            fprintf(audit, "time_s,dtime_s,y_at_time_minus_dtime_m,y_at_time_m,vy_step_average_m_s\n");
    }
    if (audit != NULL && (last_time < 0.0 || fabs(time - last_time) > 1.0e-10)) {
        fprintf(audit, "%.12g,%.12g,%.12g,%.12g,%.12g\n", time, dtime, y0, y1, vy);
        fflush(audit);
        last_time = time;
    }
#endif
}
