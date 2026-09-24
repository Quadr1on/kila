import type { NavItem } from "@/lib/nav";

/** Honest placeholder: says what the page will do and which phase delivers it. */
export function PlannedPage({ item, bullets }: { item: NavItem; bullets: string[] }) {
  return (
    <section className="mt-6 border border-dashed border-rule bg-sheet/60 px-6 py-8">
      <div className="cell-label">Not built yet · arrives in phase {item.livePhase}</div>
      <p className="mt-2 max-w-[60ch] text-[15px]">
        This page is a placeholder. Nothing here is simulated; it will stay empty until phase {item.livePhase}{" "}
        ships the real feature.
      </p>
      <ul className="mt-4 space-y-1.5 text-muted">
        {bullets.map((b) => (
          <li key={b} className="flex gap-2">
            <span aria-hidden className="text-rule">
              —
            </span>
            {b}
          </li>
        ))}
      </ul>
    </section>
  );
}
