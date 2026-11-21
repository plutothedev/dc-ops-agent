<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-01: High Supply Air Temperature / CRAH Failure

## Symptoms
- CRAH or CRAC unit alarm: fan failure, fan fault, or unit shutdown.
- Supply air temperature above setpoint on the failed unit, or return air temperature rising.
- Rack inlet temperature climbing in the aisles served by the unit; hot spots at the end of the row.
- Airflow reading on the unit drops to zero or far below its normal range.

## Immediate actions
- Confirm the alarm is real: check the unit display and the supply and return air sensors.
- Check whether neighboring cooling units are running and can absorb the load.
- Raise the setpoint or fan speed on healthy units if the controls allow it.
- Open blanking panels or doors only as directed; keep containment intact.
- Watch rack inlet temperature every few minutes and note the trend.

## Diagnosis
- Read the fan status, motor current and drive fault code on the unit.
- Check the unit breaker and supply voltage: a tripped breaker points upstream, a drive fault points at the fan.
- Compare chilled water valve position and water temperatures to rule out a cooling coil problem.
- Check for a failed belt, seized bearing, or an unexpected safety interlock.
- Compare airflow before and after the alarm to size the lost capacity.

## Recovery
- Reset the drive or breaker once only if there is no sign of a short or burning smell.
- Start the standby unit or raise output on the remaining units.
- Replace the failed fan or motor under lockout and tagout.
- Verify supply air temperature and airflow return to normal range before clearing the alarm.

## Escalation
- Escalate to facilities mechanical if the unit cannot be restarted within 15 minutes.
- Escalate to the site manager if rack inlet temperature approaches the allowable limit.
- Notify the IT owners of affected racks so they can prepare to shed load.
