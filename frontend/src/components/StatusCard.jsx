export default function StatusCard({ label, value, accent = "slate" }) {
  const accents = {
    slate: "border-slate-700 text-slate-100",
    teal: "border-teal-700 text-teal-300",
    amber: "border-amber-700 text-amber-300",
    rose: "border-rose-700 text-rose-300",
  };
  return (
    <div className={`rounded-xl border bg-slate-900/60 p-4 ${accents[accent]}`}>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </div>
  );
}
