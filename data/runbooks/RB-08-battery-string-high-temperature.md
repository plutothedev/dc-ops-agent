<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-08: Battery String High Temperature

## Symptoms
- UPS battery cabinet or string temperature alarm above the limit.
- Cell or jar temperature rising, bulging cases, or an acrid smell.
- Battery room temperature high, or charge current high relative to temperature.
- Float voltage low or high for the temperature.

## Immediate actions
- Check the battery room temperature and ventilation.
- Do not open a hot cabinet; keep people away if there is a smell, smoke, or swelling.
- Note the temperature trend and whether charging is active.
- Notify the electrical on-call.
- Be ready to take the string offline on advice.

## Diagnosis
- Compare the string temperature to the room temperature and to other strings.
- Check the charger voltage and current for overcharge or a thermal runaway sign.
- Check for a failed cooling unit or blocked airflow in the battery room.
- Inspect for swollen cells, leaks, or loose terminals when it is safe to do so.
- Review recent discharge events and the battery age.

## Recovery
- Restore battery room cooling and ventilation.
- Isolate the affected string only under the UPS vendor guidance.
- Replace failed cells or strings under the approved procedure.
- Verify temperature and float voltage return to normal before returning to service.

## Escalation
- Escalate immediately to the electrical on-call for smoke, swelling, or a rapid rise.
- Call emergency services for fire or smoke.
- Notify the UPS vendor and the site manager.
