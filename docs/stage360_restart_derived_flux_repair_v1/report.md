# Stage 360 derived-flux restart repair

Stage360 creates a fresh offline candidate from the actual 79.995 s saved
state. It removes only `phi`, `meshPhi`, and `Uf`, which are derived flux/face
fields that can be regenerated from the retained mesh, displacement, velocity,
pressure, and force fields. No physical parameter, time step, threshold, or
protected runtime is changed. A new explicit Smoke authorization is required.
