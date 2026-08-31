# Stage 361 derived-flux-free restart Smoke

Stage361 runs one fresh 40-step Smoke from the Stage360 candidate at 79.995 s
to 80.195 s. The restart retains solved fields and removes only `phi`,
`meshPhi`, and `Uf`; OpenFOAM is expected to regenerate these derived fields
for the current mesh. This stage never starts continuation automatically.
