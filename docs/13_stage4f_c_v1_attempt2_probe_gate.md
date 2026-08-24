# Stage 4F-C-v1 attempt2 probe gate

The single authorized automatic R2021b probe did not pass, so attempt2 A was
not started. MATLAB was launched from the isolated D-drive runtime, but its
log reports MathWorks ApplicationService communication error `5001`.

The probe wrapper then hit a PowerShell naming error after launch because the
temporary variable name `$pid` collides with PowerShell's read-only automatic
`$PID` variable. The two exact probe processes observed for that launch
(launcher `25916`, child `13440`) had exited and no residual MATLAB or
OpenFOAM process remained. Because the wrapper did not capture a return code
and did not emit the requested release/architecture/license/path markers, the
probe is classified as blocked rather than passed. No second probe was run.

The parent checkpoint and its 32-file protection set remain unchanged:

- checkpoint SHA-256: `5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e`
- normalized protection SHA-256: `9e51091ce3b62dc379769db6ff8ea0a7afe47950bb60b92615b2990ea9e2ee01`

No A/B/C branch, OpenFOAM process, CFD force, or unified checkpoint exists in
attempt2. A new authorization is required only after one clean automatic
probe records all frozen environment checks with return code zero.
