Dispatch System:
- System will provide manage daily route assignments for Drivers, Walkers and Trainers/Captains
- Surface: Program with Discord Bot Integration Capabilities
Daily Route Features:
5-7 Trucks per day
1 Driver and 2 Trainers per truck with a variable amount of regular walkers
General Requirements:
- Random daily assignments, walkers, drivers and captains are randomly assigned to a truck
- No person should be scheduled to work the same truck two days in a row
- Assignments should respect off-days and work with the context of walkers and drivers being able to call out (request daily confirmation)
- Enforce a ban-list [max 2 Walkers per Driver and 2 Drivers per Walker], do not assign walkers to drivers if either one appear on the other's ban list
*Optional Fav List [max 2 Walkers per Driver and 2 Drivers per Walker], increase the likelihood of appearing on the same truck together
Allow manual truck re-assignment or replacement for walkers/captains as an option

Other Context:
- routes are assigned 7:30am at the earliest and 8:30 am at the latest daily
- Initial assignments are placed in the "Drivers Chat" on Discord
- Confirmation requests are DM'd to individual drivers/walkers/trainers, the bots will retrieve confirmations y/n and take the following steps:
Answer No:
 -> Drivers: (usually in the case of an emergency call out) Immediately notify Dispatch and reassign an available driver from the pool or request manual assignment.
 -> Walkers: Notify Dispatch and request approval to assign another walker from the available pool or request manual assignment.
 -> Trainers: Notify Dispatch and request approval to assign another trainer from the available pool or request manual assignment.
Answer Yes:
-> Drivers: assign to truck and proceed
-> Walkers: assign to truck and proceed
-> Trainers: assign to truck and proceed   
- Driver confirmation window closes at 8:00 am, assume confirmation: yes, however notify dispatch and request another driver on reserve (in case of emergency)
- Trainer/Walker confirmation window closes at 9:30 am
- Final Assignments are issued at 10:00 am


