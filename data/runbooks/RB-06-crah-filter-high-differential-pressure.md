<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-06: CRAH Filter High Differential Pressure

## Symptoms
- Filter alarm on a cooling unit: differential pressure across the filter above the limit.
- Airflow through the unit drifts down while fan speed or current rises.
- Supply air temperature slowly rises or the return to supply difference widens.
- Pressure drop has been climbing gradually over days or weeks, not suddenly.

## Immediate actions
- Confirm the reading against the alarm limit and the last known clean-filter value.
- Check that the unit still delivers enough airflow and that supply air is within range.
- Schedule a filter change; this is rarely an emergency on its own.
- Check whether other units have similar readings.

## Diagnosis
- Compare differential pressure to its history to see the rate of rise.
- Inspect the filter bank for dust, debris, or wet media.
- Check that the pressure sensor tubing is not blocked or disconnected.
- Look for recent construction, packing material, or airflow changes near the intake.
- Check fan current to see whether the unit is working harder.

## Recovery
- Replace the filters during a planned window and verify the pressure drops to normal.
- Re-check the sensor reading and clear the alarm.
- Review the filter replacement interval.

## Escalation
- Escalate to facilities maintenance if the pressure keeps rising after a filter change.
- Escalate to the site manager if airflow loss causes high rack inlet temperature.
- Report suspected sensor faults to controls support.
