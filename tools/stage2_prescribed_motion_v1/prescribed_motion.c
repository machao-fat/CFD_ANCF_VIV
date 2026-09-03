/* Fluent compiled UDF for the Stage 2 prescribed-motion replay. */
#include "udf.h"
#include <math.h>
#include <stdio.h>

#define STAGE2_AMPLITUDE 0.10
#define STAGE2_FREQUENCY 0.16
#define STAGE2_OMEGA (2.0 * M_PI * STAGE2_FREQUENCY)

DEFINE_CG_MOTION(stage2_cylinder_motion, dt, vel, omega, time, dtime)
{
    static FILE *audit = NULL;
    real ydot = STAGE2_AMPLITUDE * STAGE2_OMEGA * cos(STAGE2_OMEGA * time);
    (void)dt; (void)dtime;
    NV_S(vel, =, 0.0);
    NV_S(omega, =, 0.0);
    vel[1] = ydot;
    if (audit == NULL) {
        audit = fopen("stage2_fluent_motion_audit.csv", "w");
        if (audit != NULL)
            fprintf(audit, "time_s,y_m,vy_m_s\n");
    }
    if (audit != NULL) {
        fprintf(audit, "%.12g,%.12g,%.12g\n", time,
                STAGE2_AMPLITUDE * sin(STAGE2_OMEGA * time), ydot);
        fflush(audit);
    }
}
