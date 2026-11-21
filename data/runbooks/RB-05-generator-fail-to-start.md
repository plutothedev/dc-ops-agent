<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-05: Generator Fail to Start

## Symptoms
- Generator alarm: failed to start, overcrank, or start failure after a utility outage.
- Engine cranks slowly or clicks; the starter battery voltage reads low.
- Repeated crank attempts are logged, then the controller locks out.
- Utility is down, the transfer switch is waiting for generator voltage, and UPS units are on battery.

## Immediate actions
- Confirm the utility outage and that the generator received a start signal.
- Check the controller for the fault code and the number of crank attempts.
- Do not keep cranking a weak engine; it drains the starter battery.
- Notify the electrical on-call and the site manager at once.
- Track UPS runtime remaining so a decision on shutdown can be made in time.

## Diagnosis
- Read starter battery voltage, charger status and the battery connections.
- Check fuel level, fuel valve, and fuel pressure.
- Check the emergency stop, the controller mode switch (auto, off, manual), and coolant or oil lockouts.
- Listen for a slow crank (weak battery), a click (starter solenoid), or no crank at all.
- Review the last test run and battery charger alarms for earlier warning.

## Recovery
- Replace or jump the starter battery if it is weak, using the approved procedure.
- Reset the lockout and attempt a manual start once the cause is fixed.
- When the generator runs, confirm voltage and frequency before transfer.
- After recovery, test the generator under load and check the battery charger.

## Escalation
- Escalate immediately to the electrical on-call and the generator vendor.
- Escalate to the site manager and IT owners if UPS runtime falls below 15 minutes.
- Request a mobile generator if utility restoration time is unknown.
