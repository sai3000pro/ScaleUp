/**
 * Presentation for `due_at`.
 *
 * `due_at` has been on `NodeProgress` and on `Quest` since the first version of
 * the contract and was rendered nowhere, which left the product showing time
 * only *after* a skill had already decayed -- an overdue count on a fading orb.
 * In a spaced-repetition app that is exactly backwards: the value of the
 * schedule is knowing what is coming while you can still act on it, which is
 * the whole reason Anki shows a forecast rather than a backlog.
 *
 * Whole days, and rounded rather than floored. The backend schedules in days
 * (`interval_days`), so sub-day precision would be false precision, and a node
 * due in 23 hours reads far better as "due tomorrow" than as "due in 0 days".
 *
 * These are called only from components that render after a client-side fetch,
 * so reading the clock here cannot desynchronise a server render from its
 * hydration.
 */

const MS_PER_DAY = 86_400_000;

/** Signed whole days until `dueAt`. Negative means overdue. `null` if unscheduled. */
export function daysUntil(dueAt: string | null, now: number = Date.now()): number | null {
  if (!dueAt) return null;
  const due = Date.parse(dueAt);
  if (Number.isNaN(due)) return null;
  return Math.round((due - now) / MS_PER_DAY);
}

/**
 * "Due today" / "Due in 3 days" / "4 days overdue", or `null` when the node has
 * never been reviewed and so has no schedule yet.
 */
export function dueLabel(dueAt: string | null, now: number = Date.now()): string | null {
  const days = daysUntil(dueAt, now);
  if (days === null) return null;
  if (days < 0) {
    const overdue = -days;
    return overdue === 1 ? "1 day overdue" : `${overdue} days overdue`;
  }
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `Due in ${days} days`;
}

/** The same thing at orb size, where 132px is the whole budget. */
export function dueLabelShort(dueAt: string | null, now: number = Date.now()): string | null {
  const days = daysUntil(dueAt, now);
  if (days === null) return null;
  if (days < 0) return `${-days}d overdue`;
  if (days === 0) return "Due today";
  return `Due in ${days}d`;
}

/**
 * Is this worth putting on the canvas?
 *
 * A node due in four months is true but not actionable, and printing it on
 * every mastered orb would bury the handful that need attention this week.
 */
export function isDueSoon(dueAt: string | null, withinDays = 7, now: number = Date.now()): boolean {
  const days = daysUntil(dueAt, now);
  return days !== null && days <= withinDays;
}
