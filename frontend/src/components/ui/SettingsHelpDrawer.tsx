import React from 'react';
import { X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// ---------------------------------------------------------------------------
// Help content registry
// ---------------------------------------------------------------------------

interface HelpEntry {
  title: string;
  summary: string;
  detail: string;
  example?: string;
  note?: string;
}

const HELP_CONTENT: Record<string, HelpEntry> = {
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
    note: 'Leave blank to disable the cutoff — assignments will remain "pending" indefinitely.',
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
  tier1_dbscan_eps: {
    title: 'Tier 1 DBSCAN Epsilon',
    summary: 'Geographic radius (in degrees) used to cluster delivery packages into tote groups.',
    detail:
      'The Tier 1 Manifest Verify system uses DBSCAN (a density-based clustering algorithm) to group packages by geographic proximity. Epsilon is the maximum distance between two packages for them to be considered part of the same cluster. 0.015 degrees ≈ ~1 mile at typical latitudes.',
    example: '"0.015" — packages within ~1 mile of each other can form a cluster.',
    note: 'Smaller values produce tighter, more precise clusters. Larger values merge neighborhoods together. Change with caution — affects tote classification results directly.',
  },
  tier1_dbscan_min_samples: {
    title: 'Tier 1 DBSCAN Min Samples',
    summary: 'Minimum number of packages needed to form a core cluster point.',
    detail:
      'In DBSCAN, a point is a "core" point if at least this many other points fall within epsilon distance. Core points seed the cluster; non-core points are either border points or outliers ("strays"). Higher values require denser areas to form clusters.',
    example: '"30" — at least 30 packages must be within 1 mile for that area to form a cluster core.',
  },
  tier1_small_tote_cutoff: {
    title: 'Small Tote Package Cutoff',
    summary: 'Maximum packages in a cluster for it to be classified as a "small tote."',
    detail:
      'After clustering, totes are classified by size. A cluster with fewer packages than this threshold is a small tote. Small totes receive different stray/uncertain tolerance rules because they are inherently lower-density.',
    example: '"10" — clusters of 10 or fewer packages are small totes.',
  },
  tier1_small_stray_max: {
    title: 'Small Tote Max Strays',
    summary: 'Maximum stray packages allowed in a small tote before it is flagged.',
    detail:
      'Stray packages are outlier points that DBSCAN could not assign to any cluster. In a small tote, even 1–2 strays can be a meaningful percentage of the load. This threshold controls how many are acceptable before raising a verification flag.',
    example: '"1" — more than 1 stray package in a small tote triggers a flag.',
  },
  tier1_small_uncertain_max: {
    title: 'Small Tote Max Uncertain',
    summary: 'Maximum uncertain packages allowed in a small tote.',
    detail:
      'Uncertain packages are border points — they fall within range of a cluster but do not have enough nearby neighbors to be core points. In small totes, too many uncertain packages suggest poor geographic coherence.',
    example: '"3"',
  },
  tier1_stray_pct: {
    title: 'Stray Package % Threshold',
    summary: 'Maximum stray packages as a fraction of tote size for large totes.',
    detail:
      'For totes larger than the small tote cutoff, the stray threshold is expressed as a percentage of the total package count. This scales naturally with tote size — a large route can tolerate more strays in absolute terms.',
    example: '"0.10" — at most 10% of packages in a large tote can be strays.',
  },
  tier1_uncertain_pct: {
    title: 'Uncertain Package % Threshold',
    summary: 'Maximum uncertain packages as a fraction of tote size for large totes.',
    detail:
      'Same concept as the stray percentage, but for uncertain (border-point) packages. Higher values allow more geographic looseness in cluster assignment.',
    example: '"0.40" — up to 40% of packages can be uncertain in a large tote.',
  },
  effort_time_factor: {
    title: 'Effort Time Factor',
    summary: 'Weight applied to time-based components when computing route effort scores.',
    detail:
      'Controls how much the time spent on a route (total hours, stop duration) contributes to the final effort score. A value of 1.0 means time is the sole driver; 0.0 means time is ignored entirely. Combine with Effort Physical Factor — the two do not need to sum to 1.',
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
  discord_role_captain: {
    title: 'Captain Role ID',
    summary: 'Discord role ID for captain/lead employees.',
    detail: 'Used for notifications targeted at crew leads or captain-tier employees.',
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
                  onClick={onClose}
                  className="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                >
                  <X className="w-4 h-4" />
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
                    <p className="text-sm text-foreground leading-relaxed">
                      {entry.detail}
                    </p>
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

                  {/* Note */}
                  {entry.note && (
                    <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2.5">
                      <span className="text-warning text-xs font-bold mt-0.5">Note</span>
                      <p className="text-xs text-foreground leading-relaxed">{entry.note}</p>
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
