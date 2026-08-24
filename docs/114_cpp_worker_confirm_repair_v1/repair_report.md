# C++ worker confirm repair

The one-shot confirm failed closed at global step 561 because a typed MotionRecord crossed the persistent backend mapping boundary. The adapter now serializes that record before begin_step. Specialized offline tests and the full unittest suite pass. No real process was started after cleanup; a new explicit authorization is required before another confirm.
