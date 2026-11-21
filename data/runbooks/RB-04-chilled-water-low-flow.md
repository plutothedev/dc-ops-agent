<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-04: Chilled Water Low Flow

## Symptoms
- Chilled water flow below minimum, low flow alarm on the chiller, or flow switch open.
- Pump alarm: a chilled water pump has stopped, tripped, or shows no motor current.
- Differential pressure across the loop collapses; chiller leaving water temperature rises.
- Chiller may trip on low evaporator flow; CRAH coils warm up and supply air temperature rises.
- A standby pump has not started automatically.

## Immediate actions
- Check which pumps are running and whether the standby pump should have started.
- Start the standby chilled water pump manually if the controls allow.
- Reduce chiller load or stage cooling as directed to protect the evaporator.
- Verify the loop isolation valves are in the expected position.
- Watch room temperatures on cooling units fed by the loop.

## Diagnosis
- Read the pump motor current, drive status and fault code on the failed pump.
- Check the pump breaker and the control power for the pump starter.
- Verify the flow, supply and return pressure and temperature readings along the loop.
- Look for a closed valve, a strainer blockage, or air in the system.
- Check why the standby pump did not start: lead-lag sequence, auto mode, or a lockout.

## Recovery
- Restart or reset the pump once if there is no mechanical or electrical fault evident.
- Run the standby pump and confirm flow returns to the normal range.
- Repair or replace the failed pump motor, starter, or coupling under lockout and tagout.
- Restart the chiller after flow is proven and confirm leaving water temperature falls.

## Escalation
- Escalate to facilities mechanical for any pump that will not start.
- Escalate to the site manager if the chiller stays off and room temperatures are rising.
- Call the chiller or pump vendor if flow is present but the flow switch will not clear.
