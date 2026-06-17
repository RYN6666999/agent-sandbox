import { useEffect, useState } from "react";

export function Splash({ onDone }: { onDone: () => void }) {
  const [out, setOut] = useState(false);

  useEffect(() => {
    const t1 = setTimeout(() => setOut(true), 1100);
    const t2 = setTimeout(onDone, 1450);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [onDone]);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 999,
      background: "#ede8e0",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14,
      transition: "opacity 0.35s ease",
      opacity: out ? 0 : 1,
      pointerEvents: out ? "none" : "auto",
    }}>
      <style>{`
        @keyframes rise { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        @keyframes dot  { 0%,80%,100%{opacity:.2}40%{opacity:.8} }
        .sp-logo { animation: rise 0.45s cubic-bezier(.34,1.4,.64,1) both; }
        .sp-name { animation: rise 0.45s .08s ease both; }
        .sp-dots { animation: rise 0.45s .16s ease both; }
        .d1{animation:dot 1.1s 0s infinite}
        .d2{animation:dot 1.1s .18s infinite}
        .d3{animation:dot 1.1s .36s infinite}
      `}</style>
      <div className="sp-logo" style={{
        width: 44, height: 44, borderRadius: 10,
        background: "#3d352a",
        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22,
      }}>🧠</div>
      <div className="sp-name" style={{ fontSize: 14, fontWeight: 500, color: "#3d352a", letterSpacing: ".03em" }}>
        AgentOS
      </div>
      <div className="sp-dots" style={{ display: "flex", gap: 5 }}>
        {(["d1", "d2", "d3"] as const).map((c) => (
          <span key={c} className={c} style={{
            width: 5, height: 5, borderRadius: "50%", background: "#a89a8a", display: "inline-block",
          }} />
        ))}
      </div>
    </div>
  );
}
