// One drawn icon set: 1.5px strokes, square caps, 16px grid.
type P = { className?: string };
const base = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor",
  strokeWidth: 1.5, strokeLinecap: "square" as const, "aria-hidden": true };

export const ArrowRight = ({ className }: P) => (
  <svg {...base} className={className}><path d="M2.5 8h10M9 4.5 12.5 8 9 11.5" /></svg>
);
export const ArrowUpRight = ({ className }: P) => (
  <svg {...base} className={className}><path d="M4.5 11.5 11 5M5.5 4.5H11.5V10.5" /></svg>
);
export const Lock = ({ className }: P) => (
  <svg {...base} className={className}><path d="M3.5 7.5h9v6h-9zM5.5 7.5V5a2.5 2.5 0 0 1 5 0v2.5" /></svg>
);
export const Cross = ({ className }: P) => (
  <svg {...base} className={className}><path d="M4 4l8 8M12 4l-8 8" /></svg>
);
export const Check = ({ className }: P) => (
  <svg {...base} className={className}><path d="M3 8.5 6.5 12 13 4.5" /></svg>
);
