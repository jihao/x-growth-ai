import type { LucideIcon } from "lucide-react";

export function Metric({ label, value }: { label: string; value: string | number | undefined }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value ?? "-"}</strong>
    </div>
  );
}

export function PanelTitle({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
  return <h2><Icon size={18} /> {title}</h2>;
}

export function EmptyState({ text }: { text: string }) {
  return <div className="empty">{text}</div>;
}
