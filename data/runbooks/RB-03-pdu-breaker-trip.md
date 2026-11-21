<!-- (C) -->
> Fictional sample runbook for dc-ops-agent. Not a real procedure.

# RB-03: PDU Breaker Trip

## Symptoms
- PDU alarm: breaker open, branch circuit tripped, or output loss on a rack feed.
- One or more racks show a lost power feed; servers fall back to their other feed or go down.
- Branch current was high or rising before the trip.
- A single-corded device or one rack lost power while upstream units look normal.

## Immediate actions
- Identify which branch circuit and which racks are affected.
- Check that dual-corded equipment is running on its other feed.
- Do not reclose the breaker yet; the trip may be a real overload or short.
- Notify the IT owners of the affected racks.
- Record the load on the sibling PDU so it is not overloaded by failover.

## Diagnosis
- Read the branch current history before the trip to tell overload from a short circuit.
- Inspect the cords, power strips and recently added equipment on that branch.
- Look for a burnt smell, heat, or discoloration at the breaker and receptacles.
- Compare the load to the breaker rating and the derating rule for continuous load.
- Check the upstream UPS output for any disturbance that coincided with the trip.

## Recovery
- Move or remove the offending load, then reclose the breaker once.
- If it trips again, leave it open and call for an electrician.
- Rebalance load across branches and across the A and B paths.
- Confirm all equipment is back on dual feeds and clear the alarm.

## Escalation
- Escalate to the electrical on-call for any repeat trip or signs of heat or arcing.
- Escalate to the site manager if single-corded equipment is down.
- Notify the customer or service owner of affected racks.
