<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-09: ATS Transfer Failure

## Symptoms
- Automatic transfer switch alarm: failed to transfer, stuck on utility, or in a fault position.
- Generator is running and healthy but the load remains without power from it.
- UPS units are on battery and runtime remaining is falling after a utility outage.
- Source availability shows utility lost and generator available, with no transfer.

## Immediate actions
- Check the transfer switch display for the position, source status, and fault code.
- Confirm the generator voltage and frequency are within range.
- Check whether the switch is in auto mode and not locked out or in test.
- Notify the electrical on-call and prepare for a manual transfer.
- Track UPS runtime remaining.

## Diagnosis
- Read the source voltage on both utility and generator sides at the switch.
- Check the transfer delay timers and the retransfer settings.
- Look for a control power fault, a blown fuse, or a mechanical interlock.
- Check the position indicators and the transfer signal from the generator controller.
- Compare the event log to see whether a transfer was attempted.

## Recovery
- Perform a manual transfer only by an authorized electrician and per the switch procedure.
- After the load is on the generator, confirm UPS units return to normal input.
- Repair the control fault, then test the transfer under controlled conditions.
- Return the switch to auto and document the cause.

## Escalation
- Escalate immediately to the electrical on-call and the switchgear vendor.
- Escalate to the site manager if UPS runtime is below 10 minutes.
- Do not operate the switch manually without a qualified electrician.
