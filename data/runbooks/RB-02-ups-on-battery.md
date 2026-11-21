<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-02: UPS On Battery

## Symptoms
- UPS alarm: on battery, input power fail, or input out of tolerance.
- Output load is carried by the battery; battery runtime remaining counts down.
- Possible companion alarms: utility power loss, generator running, or an automatic transfer switch alarm.
- Battery charge percentage falls steadily while load stays flat.

## Immediate actions
- Note the time the unit went to battery and the runtime remaining.
- Check whether the utility is down or only a brief dip occurred.
- Confirm the standby generator has started and is supplying voltage.
- Do not add load to units running on battery.
- Notify IT owners that a power event is under way.

## Diagnosis
- Read the input voltage and frequency at the UPS and at the transfer switch.
- Check the upstream breaker, utility feed status, and generator output.
- Compare runtime remaining to the expected generator start and transfer time.
- If the generator is healthy but the UPS stays on battery, suspect the transfer switch (see the transfer failure runbook).
- Review the UPS event log for the first input fault recorded.

## Recovery
- When input power returns, the UPS transfers back and recharges its battery automatically.
- Confirm input voltage is stable before leaving manual bypass or clearing alarms.
- Let batteries recharge before accepting a second outage; log the discharge depth.
- Record the event with times, load, and the runtime consumed.

## Escalation
- Escalate immediately to the electrical on-call if runtime remaining drops below 10 minutes.
- Escalate to the site manager before any planned load shed.
- Call the UPS vendor if the unit transfers to battery with healthy input power.
