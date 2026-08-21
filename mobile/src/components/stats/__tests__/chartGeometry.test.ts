/**
 * Line-chart point geometry (ADR-271 §V).
 *
 * The dots must land on the same x as their axis labels. The labels are a flex
 * row of N equal cells with the text centred, so label i sits at (i + 0.5)/N of
 * the width — but the chart originally spaced its points PAD..W-PAD, which puts
 * point 0 hard against the left edge and point N-1 against the right.
 *
 * The drift was ~15px at the ends and ~0 in the middle, which is exactly why it
 * survived review: the centre of the chart looked perfect.
 *
 * Pure arithmetic, so it is worth pinning — a future "tidy up the padding"
 * cannot silently reintroduce it.
 */

/** Cell-centre x, shared by the svg and the label row. */
export function pointX(i: number, width: number, n: number): number {
  return (width / n) * (i + 0.5);
}

/** Where a flex row of n equal cells centres its i-th label. */
function labelCentre(i: number, width: number, n: number): number {
  return (width * (i + 0.5)) / n;
}

/** The OLD, buggy geometry — kept so the test states what it is preventing. */
function edgeToEdgeX(i: number, width: number, n: number, pad: number): number {
  return pad + i * ((width - pad * 2) / (n - 1));
}

describe('line chart point geometry', () => {
  const W = 640, N = 12, PAD = 12;

  it('places every point exactly on its label centre', () => {
    for (let i = 0; i < N; i++) {
      expect(pointX(i, W, N)).toBeCloseTo(labelCentre(i, W, N), 6);
    }
  });

  it('never drifts, at any width or bucket count', () => {
    // Weeks in a month (4-6), days in a week (7), months in a year (12).
    for (const n of [4, 5, 6, 7, 12]) {
      for (const w of [320, 393, 640, 1200]) {
        for (let i = 0; i < n; i++) {
          expect(pointX(i, w, n)).toBeCloseTo(labelCentre(i, w, n), 6);
        }
      }
    }
  });

  it('documents the drift the old geometry produced', () => {
    // Worst at the ENDS, ~zero in the middle — which is how it passed review.
    const drift = (i: number) => edgeToEdgeX(i, W, N, PAD) - labelCentre(i, W, N);
    expect(Math.abs(drift(0))).toBeGreaterThan(14);        // Jan, left of label
    expect(Math.abs(drift(N - 1))).toBeGreaterThan(14);    // Dec, right of label
    expect(Math.abs(drift(Math.floor(N / 2)))).toBeLessThan(2);  // mid: fine
  });

  it('keeps the first and last points inside the plot', () => {
    // Cell centres inset by half a cell, so nothing is clipped at the edge.
    expect(pointX(0, W, N)).toBeGreaterThan(0);
    expect(pointX(N - 1, W, N)).toBeLessThan(W);
  });
});
