import React from 'react';
import { X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// ---------------------------------------------------------------------------
// Help content registry
// ---------------------------------------------------------------------------

interface HelpEntry {
  title: string;
  summary: string;
  /** Plain text, or ReactNode when a rule needs emphasis to be legible.
   *
   *  Two of these entries turn on a single word — "the pin does NOT apply", "on
   *  the specified weekdays ONLY" — and a dispatcher skimming a paragraph reads
   *  straight past it. Where that word carries the rule, it is marked. */
  detail: string | React.ReactNode;
  example?: string;
  note?: string | React.ReactNode;
  /** Notes default to warning amber. `danger` is for a note describing something
   *  that silently STOPS working — a deactivated crew pin looks identical to one
   *  that never existed, so it earns the stronger colour. */
  noteTone?: 'warning' | 'danger';
}

const HELP_CONTENT: Record<string, HelpEntry> = {
  crew_pin: {
    title: 'Crew Pins',
    summary: 'A pinned crew works the same truck every day that the driver is dispatched.',
    detail: (
      <>
        <p>
          Pins are applied immediately after driver assignment runs, so the
          members are placed on the driver's truck directly.
        </p>
        <p className="font-semibold text-foreground">The driver is the anchor</p>
        <p>
          If the driver is off that day, then the pin{' '}
          <span className="text-danger font-semibold">does not</span> apply and
          members are dispatched normally.
        </p>
      </>
    ),
    example:
      'Pin a Captain, Trainer and two Walkers to a Driver. They always land on the truck that driver is assigned to, every time that driver is on shift.',
    // Danger, not warning: a deactivated pin looks exactly like one that was
    // never created, so the dispatcher gets no signal that a crew stopped
    // being a crew.
    noteTone: 'danger',
    note: (
      <>
        <p>A ban between any two members deactivates this pin automatically.</p>
        <p className="mt-1.5">
          The roster is kept so you can reactivate the pin once the conflict is
          resolved and the ban is removed.
        </p>
      </>
    ),
  },
  truck_pin: {
    title: 'Truck Pins',
    summary: 'Assigns the crew member to the specified truck on the days indicated.',
    detail: (
      <>
        <p>
          A truck pin holds the crew member to the truck itself, on the
          specified weekdays{' '}
          <span className="font-semibold text-foreground">only</span>.
        </p>
        <p>On any other day the person is assigned normally.</p>
      </>
    ),
    example:
      'Tom is pinned to the Hub on Tuesdays and Thursdays. If he is on shift Friday or Sunday, he is dispatched by the regular rules.',
    note: (
      <>
        <p>A person can hold a crew pin or a truck pin but not both.</p>
        <p className="mt-1.5">
          A pin does not reserve the truck. If the pinned person is off, then
          the truck is dispatched as usual.
        </p>
      </>
    ),
  },
  separation: {
    title: 'Separations',
    summary: 'Keeps two people off the same crew, without telling either of them.',
    detail: (
      <>
        <p>
          Effectively works like a ban: dispatch will not place these two
          members together.
        </p>
        <p>
          The difference is that a separation is your decision about both
          members, so it does not appear in either member's list and does not
          use up either of their two bans.
        </p>
      </>
    ),
    example:
      "Two walkers who feed each other's worst habits on a route. Separate them, and neither sees anything change.",
    note: 'Only dispatch, management and admin can see separations. If either person is in a pinned crew with the other, that pin is deactivated automatically.',
  },
  shift_start: {
    title: 'Shift Start Time',
    summary: 'When drivers are expected to arrive at the offsite for the start of their shift.',
    detail:
      'This is the official start-of-day time for your operation. It is used as the anchor point for check-in compliance reports and for calculating whether a driver\'s morning photo was submitted on time.',
    example: '"07:00" — drivers must be on-site by 7 AM.',
    note: 'Leave blank if your operation does not track shift timing.',
  },
  shift_end: {
    title: 'Shift End Time',
    summary: 'The expected end of the working shift.',
    detail:
      'Used in reporting and analytics as the official close-of-day marker. Routes that are still open past this time may trigger late-completion alerts.',
    example: '"18:00" — the shift is expected to wrap by 6 PM.',
  },
  checkin_open: {
    title: 'Check-in Opens',
    summary: 'Earliest time the morning check-in photo is accepted.',
    detail:
      'Submissions before this window are rejected as "too early." This prevents drivers from checking in the night before. Set it to roughly 30–60 minutes before shift start.',
    example: '"06:30" — photos can be submitted starting at 6:30 AM.',
  },
  checkin_close: {
    title: 'Check-in Closes',
    summary: 'Deadline for the morning check-in photo.',
    detail:
      'Submissions after this time are accepted but flagged as late. Management can review these flags in the Walker Performance and Incidents pages. Typically set 15–30 minutes after shift start.',
    example: '"07:30" — submissions after 7:30 AM are flagged.',
  },
  dispatch_confirmation_cutoff: {
    title: 'Dispatch Confirmation Cutoff',
    summary: 'The time by which employees must accept or decline their dispatch assignment.',
    detail:
      'When dispatch assignments are published to Discord, each employee receives a notification and is expected to confirm. If no response is received by this cutoff time, the assignment is treated as a pending rejection and flagged for reassignment. This allows dispatch to catch problems before routes depart.',
    example: '"09:00" — employees must confirm or reject before 9 AM. Unresponded assignments are flagged.',
    note: 'Leave blank to disable the cutoff. Assignments then stay "pending" indefinitely.',
  },
  late_window_minutes: {
    title: 'Late Window',
    summary: 'Grace minutes past shift start before a crew arrival is marked “late.”',
    detail:
      'Attendance is measured against max(shift start, when the AP was established). A station-caused late start (a late AP) therefore shifts everyone\'s clock later automatically, and on-time crew are never penalised for it. Within this window past that reference, an arrival is "present"; beyond it, "late" (still not NCNS).',
    example: '"20" — arrivals up to 20 min past the reference are on-time; later is late.',
  },
  ncns_cutoff_minutes: {
    title: 'NCNS Cutoff',
    summary: 'Minutes past shift start before an unaccounted crew member is a no-call-no-show.',
    detail:
      'Measured from the same reference as the late window, max(shift start, AP established), so it AUTO-EXTENDS on a late station AP (the rare Amazon/station-fault allowance; a captain can roll-call at the AP even before the driver "arrived"). Dispatch/admin can still override an individual with a manual roll-call. IMPORTANT: the NCNS cutoff must be set BEFORE any check-in deadline is accepted, and Check-In #1 can never be earlier than it. A check-in cannot be required before crew attendance is decided.',
    example: '"60" — unaccounted crew are NCNS 60 min after shift start (later if the AP was late).',
    note: 'Set this first. The Check-in Deadlines editor is disabled until it exists.',
  },
  check_in_deadlines: {
    title: 'Check-in Deadlines',
    summary: 'Ordered mid-shift check-ins, each with its own deadline.',
    detail:
      'Add check-ins one at a time; each is the next in sequence and its deadline must be LATER than the previous. Deadlines are minutes past shift start (shown as a clock time), anchored the same way as the NCNS cutoff, so Check-In #1 auto-extends on a late station AP too. Check-In #1 also carries the completed Crew Roster + uniform/cart-cover compliance to Dispatch, so its deadline must be at or after the NCNS cutoff (crew must be decided first). Remove from the end so the earlier deadlines keep their order.',
    example: 'NCNS 60 → Check-In #1 at 75 min, #2 at 180 min, #3 at 300 min.',
    note: 'Requires the NCNS cutoff to be set and saved first.',
  },
  rating_window_hours: {
    title: 'Walker Rating Window',
    summary: 'How long after a driver departs can walker ratings still be submitted.',
    detail:
      'Drivers submit ratings for their walkers after the route is complete. This window controls how long that submission remains open. A window that is too short may cause missed ratings; too long allows ratings to be submitted well after the fact, reducing accuracy.',
    example: '"6" — drivers have 6 hours after departure to rate their walkers.',
  },
  flag_threshold: {
    title: 'Walker Rating Flag Threshold',
    summary: 'How far a single rating can deviate from a driver\'s average before it is flagged as an anomaly.',
    detail:
      'Each driver has a rolling average rating they give. If a single rating deviates from that average by more than this threshold, it is flagged for manager review. This catches unusually high or low ratings that may indicate a personal bias or a genuine performance issue.',
    example: '"1.0" — a rating of 2 from a driver whose average is 4 would flag (deviation = 2.0 > 1.0).',
  },
  graduation_assignments: {
    title: 'Graduation Threshold',
    summary: 'Successful dispatch days required before a trainee can graduate to walker.',
    detail:
      'A trainee must be assigned to and complete this many dispatch days across all training phases before they become eligible for graduation. The count increments only on days where the trainee is dispatched and the day closes without an incident report.',
    example: '"5" — a trainee needs 5 clean dispatch days to graduate.',
  },
  debt_escalation_threshold: {
    title: 'Debt Escalation Threshold',
    summary: 'Consecutive days a mandatory training task can remain incomplete before it escalates.',
    detail:
      'Training tasks can accumulate as "debt" if not completed. When the same task remains incomplete for this many consecutive days, it is automatically escalated to a manager review flag. This prevents training debts from silently piling up.',
    example: '"3" — a task that has been incomplete for 3 days in a row triggers an escalation.',
  },
  phase4_pass_score: {
    title: 'Phase 4 Pass Score',
    summary: 'Minimum percentage required on the Phase 4 practical observation to pass.',
    detail:
      'Phase 4 is a trainer-observed evaluation where the trainee is scored on real-world performance. They must meet or exceed this threshold to progress to the graduation quiz. Set this value based on your company\'s standards.',
    example: '"90" — trainees must score at least 90% to pass Phase 4.',
  },
  underperforming_trainer_threshold: {
    title: 'Underperforming Trainer Threshold',
    summary: 'Number of below-average training records before a trainer is flagged.',
    detail:
      'The system tracks each trainer\'s scores across training sessions. If a trainer accumulates this many sessions where their trainees consistently score below average, the trainer is flagged for management review.',
    example: '"3" — a trainer with 3 or more low-scoring sessions is flagged.',
  },
  max_training_phase: {
    title: 'Max Training Phase',
    summary: 'The highest phase number in your training curriculum.',
    detail:
      'Training phases are numbered starting at 1. This setting tells the system how many phases exist so it can correctly determine when a trainee has completed the full curriculum.',
    example: '"4" — training has 4 phases (1 through 4).',
  },
  dispatch_weight_driver: {
    title: 'Driver Preference Weight',
    summary: 'How strongly a driver\'s preference history influences their dispatch pairing.',
    detail:
      'The dispatch algorithm scores potential crew assignments based on mutual preference history. This weight controls how much a driver\'s historical preference (who they\'ve been paired with and liked) influences the final score for driver-role employees.',
    example: '"0.70" — driver preferences account for up to 70% of the preference score component.',
  },
  dispatch_weight_trainer: {
    title: 'Trainer Preference Weight',
    summary: 'Same preference weight applied to trainer-role employees.',
    detail:
      'Trainers are often paired with trainees, so their preference history may matter differently from a driver\'s. Set lower if you want the algorithm to rotate trainers more freely.',
    example: '"0.50"',
  },
  dispatch_weight_walker: {
    title: 'Walker Preference Weight',
    summary: 'Preference weight for walker-role employees.',
    detail:
      'Walkers typically rotate between trucks more frequently. A lower weight here reduces preference "stickiness" for walkers and keeps assignments more diverse.',
    example: '"0.30"',
  },
  dispatch_mutual_bonus: {
    title: 'Mutual Preference Bonus',
    summary: 'Score bonus when two crew members have mutually listed each other.',
    detail:
      'If employee A has listed employee B as a preference AND employee B has listed employee A, the algorithm adds this bonus to their combined score. This rewards reciprocal pairings.',
    example: '"0.10" — mutual pairs receive +0.10 added to their score.',
  },
  dispatch_tridirectional_bonus: {
    title: 'Three-Way Preference Bonus',
    summary: 'Score bonus when all three crew members mutually prefer each other.',
    detail:
      'An extension of the mutual bonus: if driver, walker, and trainer all have each other in their preference lists, this larger bonus is applied. Encourages stable, harmonious crews.',
    example: '"0.20" — a fully mutual three-way crew gets +0.20.',
  },
  dispatch_consecutive_penalty: {
    title: 'Consecutive Truck Penalty',
    summary: 'Score deduction when an employee is assigned the same truck as the previous day.',
    detail:
      'Variety in truck assignment can improve employee experience and reduce territorial disputes. This penalty slightly discourages re-assigning the exact same people to the same truck on back-to-back days.',
    example: '"0.05" — consecutive same-truck pairings receive −0.05.',
  },
  dispatch_weight_cap: {
    title: 'Maximum Preference Score Cap',
    summary: 'The ceiling on any individual preference score contribution.',
    detail:
      'Without a cap, extremely well-matched employees with long preference histories could dominate assignments. This cap ensures the algorithm still considers new pairings fairly.',
    example: '"0.85" — no preference component can exceed 0.85.',
  },
  driver_checkin_count: {
    title: 'Driver Mid-Shift Check-ins',
    summary: 'How many structured check-in photos a driver is expected to submit during the day.',
    detail:
      'Beyond the morning check-in, drivers can be required to submit photos at intervals during the route (e.g., at parcel delivery handoff points or at route milestones). This count sets the expectation; missing check-ins are tracked as compliance events.',
    example: '"4" — driver is expected to submit 4 check-in photos across the shift.',
    note: 'Set to 0 to disable mid-shift check-ins entirely.',
  },
  effort_time_factor: {
    title: 'Effort Time Factor',
    summary: 'Weight applied to time-based components when computing route effort scores.',
    detail:
      'Controls how much the time spent on a route (total hours, stop duration) contributes to the final effort score. A value of 1.0 means time is the sole driver; 0.0 means time is ignored entirely. Combine with Effort Physical Factor. The two do not need to sum to 1.',
    example: '"0.5" — time and physical effort contribute equally.',
  },
  effort_physical_factor: {
    title: 'Effort Physical Factor',
    summary: 'Weight applied to physical-exertion components when computing route effort scores.',
    detail:
      'Controls how much the physical demands of a route (stairs, elevator waits, package weight class) contribute to the final effort score. A value of 1.0 means physical effort is the sole driver; 0.0 means it is ignored.',
    example: '"0.5" — time and physical effort contribute equally.',
  },
  ingestion_mode: {
    title: 'Manifest Ingestion Mode',
    summary: 'Whether manifests are ingested from file uploads or pulled via API.',
    detail:
      '"file" mode means dispatch uploads a manifest file (CSV/Excel) each morning. "api" mode means AsheFlow fetches the manifest automatically via an external API integration. The "api" mode requires additional configuration of your logistics provider\'s API credentials.',
    example: '"file" — dispatch manually uploads the day\'s manifest each morning.',
    note: '"api" mode is only available if an API integration has been provisioned for your account.',
  },
  discord_guild_id: {
    title: 'Discord Server ID (Guild ID)',
    summary: 'The numeric ID of your Discord server.',
    detail:
      'Every Discord server has a unique Guild ID. AsheFlow uses this to connect to your server and send notifications. To find it: in Discord, enable Developer Mode (User Settings → Advanced → Developer Mode), then right-click your server icon and choose "Copy Server ID."',
    example: '"1234567890123456789"',
  },
  discord_drivers_channel_id: {
    title: 'Drivers Channel ID',
    summary: 'The Discord channel where driver dispatch notifications are posted.',
    detail:
      'When dispatch assignments are published, driver-specific notifications (including shift assignments, route details, and confirmation requests) are sent to this channel.',
    example: 'Right-click the #drivers channel in Discord → "Copy Channel ID."',
  },
  discord_trainers_channel_id: {
    title: 'Trainers Channel ID',
    summary: 'The Discord channel where trainer assignments and training updates are posted.',
    detail:
      'Trainer-role notifications (trainee assignments, phase completions, graduation quiz results) are posted here.',
  },
  discord_captains_channel_id: {
    title: 'Captains Channel ID',
    summary: "The Discord channel where the day's captain roster is posted.",
    detail:
      'At finalize, each truck and its captain is posted here. If this is unset, no captain roster is posted. Nothing else breaks.',
  },
  discord_general_channel_id: {
    title: 'General Channel ID',
    summary: 'Fallback channel for company-wide announcements.',
    detail:
      'Used for broadcasts that aren\'t role-specific, such as schedule-change announcements or general operational alerts.',
  },
  discord_invite_channel_id: {
    title: 'Invite Channel ID',
    summary: 'The channel where new employee invite links are posted.',
    detail:
      'When a new employee is bootstrapped into the system, their registration invite link is optionally posted to this channel so existing team members are aware of the new addition.',
  },
  discord_role_admin: {
    title: 'Admin Role ID',
    summary: 'The Discord role ID corresponding to your admin employees.',
    detail:
      'AsheFlow can @mention role groups when sending notifications. Set this to the Discord role that represents admins in your server. Right-click the role in Server Settings → Roles to copy its ID.',
  },
  discord_role_manager: {
    title: 'Manager Role ID',
    summary: 'Discord role ID for management employees.',
    detail: 'Used for @mentioning management in notifications and alerts.',
  },
  discord_role_asheflow: {
    title: 'AsheFlow Bot Role ID',
    summary: 'The role assigned to the AsheFlow bot itself.',
    detail:
      'When AsheFlow\'s bot is added to your server, it is typically given a dedicated role. This field stores that role\'s ID so the system can verify permissions.',
  },
  discord_role_bot: {
    title: 'Generic Bot Role ID',
    summary: 'A general "bot" role ID if applicable.',
    detail: 'Some servers have a shared "Bots" role. Use this field if your server assigns all bots to a common role.',
  },
  discord_role_dispatch: {
    title: 'Dispatch Role ID',
    summary: 'Discord role ID for dispatch employees.',
    detail: 'Dispatch-specific notifications and @mentions use this role.',
  },
  discord_role_driver: {
    title: 'Driver Role ID',
    summary: 'Discord role ID for driver employees.',
    detail: 'Used for @mentioning drivers when dispatch assignments and route notifications are sent.',
  },
  discord_role_trainer: {
    title: 'Trainer Role ID',
    summary: 'Discord role ID for trainers.',
    detail:
      'Granted and revoked automatically when someone is promoted to or moved off the trainer role. This is the role Discord previously called "Captain" — it was renamed when captains became a separate role, and the ID did not change.',
  },
  discord_role_captain: {
    title: 'Captain Role ID',
    summary: 'Discord role ID for captains, the truck route leads.',
    detail:
      'Granted and revoked automatically on promotion to or from captain. Distinct from the Trainer role: a captain leads a truck, a trainer supervises a trainee. If unset, captain promotions log a warning and grant no Discord role.',
  },
  discord_role_walker: {
    title: 'Walker Role ID',
    summary: 'Discord role ID for walker employees.',
    detail: 'Used for @mentioning walkers in dispatch notifications.',
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface SettingsHelpDrawerProps {
  fieldKey: string | null;
  onClose: () => void;
}

export default function SettingsHelpDrawer({ fieldKey, onClose }: SettingsHelpDrawerProps) {
  const entry = fieldKey ? HELP_CONTENT[fieldKey] : null;

  return (
    <AnimatePresence>
      {fieldKey && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/30 z-40"
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.div
            key="drawer"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 320, damping: 32 }}
            className="fixed right-0 top-0 h-full w-full max-w-md bg-background border-l border-border shadow-2xl z-50 overflow-y-auto"
          >
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
                    Field Reference
                  </p>
                  <h2 className="text-lg font-bold text-foreground">
                    {entry?.title ?? fieldKey}
                  </h2>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  // Icon-only: without a label a screen reader announces just
                  // "button". w-11/h-11 is 44px — the WCAG 2.5.5 minimum,
                  // which w-8 (32px) missed.
                  aria-label="Close help"
                  className="flex items-center justify-center w-11 h-11 rounded-lg hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                >
                  <X className="w-4 h-4" aria-hidden="true" />
                </button>
              </div>

              {entry ? (
                <div className="space-y-5">
                  {/* Summary */}
                  <div className="rounded-xl bg-primary/5 border border-primary/10 p-4">
                    <p className="text-sm font-medium text-foreground leading-relaxed">
                      {entry.summary}
                    </p>
                  </div>

                  {/* Detail */}
                  <div className="space-y-1.5">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      How it works
                    </p>
                    <div className="text-sm text-foreground leading-relaxed space-y-2">
                      {entry.detail}
                    </div>
                  </div>

                  {/* Example */}
                  {entry.example && (
                    <div className="space-y-1.5">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                        Example
                      </p>
                      <div className="rounded-lg bg-accent px-3 py-2.5 font-mono text-xs text-foreground">
                        {entry.example}
                      </div>
                    </div>
                  )}

                  {/* Note. Tone is per-entry: a note about something that
                      silently stops working reads as advice in amber. */}
                  {entry.note && (
                    <div
                      className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 ${
                        entry.noteTone === 'danger'
                          ? 'border-danger/30 bg-danger/5'
                          : 'border-warning/30 bg-warning/5'
                      }`}
                    >
                      <span
                        className={`text-xs font-bold mt-0.5 shrink-0 ${
                          entry.noteTone === 'danger' ? 'text-danger' : 'text-warning'
                        }`}
                      >
                        Note
                      </span>
                      <div className="text-xs text-foreground leading-relaxed">{entry.note}</div>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No documentation available for this field.</p>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
