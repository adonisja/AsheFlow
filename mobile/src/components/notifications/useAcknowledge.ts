import { useCallback, useState } from 'react';
import apiClient from '@api/client';

/**
 * The one acknowledgement call, shared by all three mobile surfaces (ADR-494 D7).
 *
 * D5 requires the two prompts to look DIFFERENT; it does not require them to
 * POST differently. The visual identity is per-component and this is not —
 * three copies of the same request is how one of them ends up sending
 * `shown_as: 'prompt'` from a gate.
 *
 * Records a CHOICE, not a read. `Notification.is_read` is set by rendering; the
 * server sets it as part of this call, so nothing here also marks read.
 *
 * ## Why a failure is NOT swallowed
 *
 * A failed read flag is cosmetic and self-corrects on the next poll. A failed
 * acknowledgement means there is no record, and for `timecard_mismatch` that
 * record is what a payroll dispute turns on — so the caller must keep the sheet
 * open rather than dismissing over a lost write.
 *
 * A 409 is the exception: the row already exists, so the thing the caller
 * wanted is true and it should proceed.
 */
export function useAcknowledge() {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const acknowledge = useCallback(async (
    notificationId: string,
    action: 'confirmed' | 'skipped' | 'unavailable',
    shownAs: 'gate' | 'prompt',
  ): Promise<boolean> => {
    setBusy(true);
    setFailed(false);
    try {
      await apiClient.post(`/notifications/${notificationId}/acknowledge`, {
        action,
        shown_as: shownAs,
      });
      return true;
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 409) return true;   // already recorded; proceed
      setFailed(true);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  return { acknowledge, busy, failed };
}
