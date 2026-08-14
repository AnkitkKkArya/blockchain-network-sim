export default function NodeSelector({ nodes, selected, onChange }) {
  return (
    <select
      value={selected}
      onChange={(e) => onChange(e.target.value)}
      className="bg-slate-800 text-slate-100 border border-slate-600 rounded-lg px-3 py-2 text-sm"
    >
      {nodes.map((url) => (
        <option key={url} value={url}>
          {url.replace("http://localhost:", "node :")}
        </option>
      ))}
    </select>
  );
}
