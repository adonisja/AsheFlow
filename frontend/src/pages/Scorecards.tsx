/**
 * Scorecards — one tab, four sub-views.
 *
 * The scorecard work landed as four separate nav entries ("Scorecard", "Crew
 * Scorecards", "Appeals", plus the entry form), which is three too many for one
 * subject and pushed the nav past what a manager can scan. They are genuinely
 * distinct pages, so they are kept as sub-tabs rather than merged into one
 * scrolling page:
 *
 *   Company    the DSP's weekly standing and metric trend      (Tier 2)
 *   Crew       individual standings, worst first               (Tier 3)
 *   Enter      record a scorecard, cross-check, open an appeal (Tier 3)
 *   Appeals    the dispute workflow                            (Tier 4)
 *
 * Sub-tab order is workflow order, not alphabetical: you read the company
 * result, look at who drove it, enter the next one, and appeal what is wrong.
 * The NAV's alphabetical rule applies to top-level tabs, which is where
 * scanning cost is paid.
 *
 * Dispatch sees only Company — individual data is management/admin per
 * docs/SCORECARD_ACCESS_MODEL.md, and the sub-tabs are filtered accordingly
 * rather than relying on the pages' own gates alone.
 */
import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import OperationsAnalytics from './OperationsAnalytics';
import ScorecardRoster from './ScorecardRoster';
import ScorecardEntry from './ScorecardEntry';
import ScorecardAppeals from './ScorecardAppeals';

type Tab = 'company' | 'crew' | 'enter' | 'appeals';

const TABS: { key: Tab; label: string; managementOnly: boolean }[] = [
  { key: 'company', label: 'Company', managementOnly: false },
  { key: 'crew',    label: 'Crew',    managementOnly: true },
  { key: 'enter',   label: 'Enter',   managementOnly: true },
  { key: 'appeals', label: 'Appeals', managementOnly: true },
];

export default function Scorecards() {
  const { groups } = useAuth();
  const isOversight = groups.includes('management') || groups.includes('admin');

  const visible = TABS.filter(t => !t.managementOnly || isOversight);
  const [tab, setTab] = useState<Tab>('company');

  // Dispatch can reach this page but only Company — if state somehow lands
  // elsewhere, fall back rather than rendering a view they cannot use.
  const active = visible.some(t => t.key === tab) ? tab : 'company';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm w-fit">
        {visible.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
              active === t.key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {active === 'company' && <OperationsAnalytics />}
      {active === 'crew'    && <ScorecardRoster />}
      {active === 'enter'   && <ScorecardEntry />}
      {active === 'appeals' && <ScorecardAppeals />}
    </div>
  );
}
