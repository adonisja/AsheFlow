import React, { useMemo, useState } from 'react';
import { useNotificationContext } from '../../contexts/NotificationContext';
import GraduationPrompt from './GraduationPrompt';
import OperatingModeChangePrompt from './OperatingModeChangePrompt';
import NotificationGate from './NotificationGate';
import ActionPrompt from './ActionPrompt';

/** Picks the one interruptive notification to show, if any (ADR-494).
 *
 *  ## Why a host rather than rendering these from the banner
 *
 *  The banner is a capped, scrollable container (ADR-487 D4a) — anything inside
 *  it can be scrolled past. An interruptive surface is the opposite kind of
 *  thing, so it mounts as a sibling, the same reasoning that put the URGENT
 *  region outside the cap.
 *
 *  ## One at a time, gates first
 *
 *  Two dialogs at once is two top-layer elements fighting, and the second is
 *  invisible until the first closes — so a gate stacked under a prompt would
 *  silently not apply. Showing exactly one, gate first, makes the order a
 *  decision rather than whatever the array happened to hold.
 *
 *  ## What this does NOT decide
 *
 *  Whether something is a gate or a prompt is the server's answer (D6). This
 *  reads `channels` and renders; it contains no expiry check, no deadline
 *  arithmetic and no "is the role guide seeded" test, because all three already
 *  happened server-side and a second copy here is the drift D6 exists to
 *  prevent.
 */
export default function InterruptiveHost() {
  const { notifications } = useNotificationContext();
  // Locally dismissed this session. The server record is what matters; this
  // only stops a dialog reappearing between the optimistic removal and the next
  // poll settling.
  const [done, setDone] = useState<Set<string>>(new Set());

  const target = useMemo(() => {
    const live = notifications.filter(n => !done.has(n.id));
    // Gates before prompts, deliberately — see the note above.
    return (
      live.find(n => n.channels.includes('gate')) ??
      live.find(n => n.channels.includes('prompt')) ??
      null
    );
  }, [notifications, done]);

  if (!target) return null;

  const finish = () => setDone(prev => new Set(prev).add(target.id));

  if (target.channels.includes('gate')) {
    return <NotificationGate notification={target} onDone={finish} />;
  }

  // Two visually distinct prompts (D5), chosen by type rather than by a shared
  // component with a prop: a congratulation and "half your app changed" must
  // not look alike.
  switch (target.type) {
    case 'graduation':
      return <GraduationPrompt notification={target} onDone={finish} />;
    case 'operating_mode_change':
      return <OperatingModeChangePrompt notification={target} onDone={finish} />;
    default:
      // ADR-505 D4. This used to `return null`, with a comment arguing that
      // rendering nothing was correct because the banner still carries the
      // message. Two things that reasoning missed, both reproduced on a device:
      //  - the registry's intent IS known: `prompt` is in `channels`, and for
      //    timecard_mismatch the PROMPT phase is the whole first half of
      //    ADR-494's escalation, which therefore never happened;
      //  - `target` is the FIRST prompt, so an invisible one hid every prompt
      //    queued behind it. A walker with an open timecard never saw their
      //    graduation.
      return <ActionPrompt notification={target} onDone={finish} />;
  }
}
