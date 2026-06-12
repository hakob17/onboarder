import { Icon } from "../icons";
import type { Tour } from "../api";

export function TourCard({ tour, idx, onIdx, onClose }: {
  tour: Tour;
  idx: number;
  onIdx: (i: number) => void;
  onClose: () => void;
}) {
  const step = tour.steps[idx];
  if (!step) return null;
  const last = idx === tour.steps.length - 1;
  return (
    <div className="tour-card" onClick={(e) => e.stopPropagation()}>
      <div className="tour-head">
        <Icon.spark style={{ width: 14, height: 14, color: "var(--brand)" }} />
        <span className="tour-eyebrow">Guided tour · {tour.title}</span>
        <button className="panel-close" onClick={onClose}><Icon.x /></button>
      </div>
      <div className="tour-title">{step.title}</div>
      <div className="tour-narration">{step.narration}</div>
      <div className="tour-foot">
        <div className="tour-dots">
          {tour.steps.map((_, i) => (
            <span key={i} className={"tour-dot" + (i === idx ? " on" : "")} onClick={() => onIdx(i)} />
          ))}
        </div>
        <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
          <button className="tbtn" disabled={idx === 0} onClick={() => onIdx(idx - 1)}>Prev</button>
          <button className="tbtn" style={{ background: "var(--brand)", color: "#fff", borderColor: "var(--brand)" }}
            onClick={() => (last ? onClose() : onIdx(idx + 1))}>
            {last ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
