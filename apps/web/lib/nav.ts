// Single source of truth for pages: sidebar entries, title-block drawing numbers,
// and which build phase makes each page real.

export type NavItem = {
  href: string;
  label: string;
  dwg: string;
  group: "Work" | "Plant" | "Assurance";
  livePhase: number; // phase in which the page becomes functional
  summary: string;
};

export const NAV: NavItem[] = [
  { href: "/workbench", label: "Workbench", dwg: "KILA-WB-001", group: "Work", livePhase: 1,
    summary: "Give KILA a task and attachments; watch the plan, tool calls and verification run." },
  { href: "/files", label: "Files", dwg: "KILA-FS-002", group: "Work", livePhase: 0,
    summary: "Everything uploaded to the Local Bucket, with previews, hashes and provenance." },
  { href: "/kb", label: "Knowledge base", dwg: "KILA-KB-003", group: "Work", livePhase: 2,
    summary: "SOPs, standards and past reports indexed for hybrid retrieval." },
  { href: "/approvals", label: "Approvals", dwg: "KILA-AP-004", group: "Work", livePhase: 4,
    summary: "Drafts waiting for a reviewer. KILA never signs anything." },
  { href: "/models", label: "Models", dwg: "KILA-MD-005", group: "Plant", livePhase: 1,
    summary: "Which local model serves each role, its health, VRAM and measured speed." },
  { href: "/router", label: "Router", dwg: "KILA-RT-006", group: "Plant", livePhase: 3,
    summary: "How tasks were classified and routed, and how often they escalated." },
  { href: "/eval", label: "Eval", dwg: "KILA-EV-007", group: "Plant", livePhase: 8,
    summary: "Golden-set accuracy, latency and escalation measured on this hardware." },
  { href: "/sovereignty", label: "Sovereignty", dwg: "KILA-SV-008", group: "Assurance", livePhase: 0,
    summary: "The tamper-evident audit ledger and evidence that nothing leaves this machine." },
];

export const CURRENT_PHASE = 3;

export function navFor(pathname: string): NavItem | undefined {
  return NAV.find((n) => pathname === n.href || pathname.startsWith(`${n.href}/`));
}
