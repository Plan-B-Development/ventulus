"""``ventulus-diag`` — the diagnostic command line for Ventulus (DEC-503).

An administrator's tool, not a second frontend. It runs the tests that
deliberately drive fans for investigation — the PWM Test Report (with its
stall/restart probe), PWM characterisation, control-path discovery and
validation sessions — and reads, exports and compares their results.

It writes nothing to hardware itself. Every test is a daemon diagnostic: the
daemon gates it, performs it and puts the header back when it ends, exactly as
for the GUI, and it does so even if this process is killed. Qt-free on purpose,
so it runs on a machine with no desktop.
"""
