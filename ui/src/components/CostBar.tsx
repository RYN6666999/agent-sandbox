import { useEffect } from "react";
import { getCost } from "../api";
import { useStore } from "../store";

export function CostBar() {
  const { cost, setCost } = useStore();

  useEffect(() => {
    const poll = () => getCost().then(setCost).catch(() => {});
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [setCost]);

  return (
    <div style={{
      padding: "4px 16px 5px",
      background: "#e8e1d8",
      borderTop: "0.5px solid #d4c9bb",
      display: "flex", gap: 16, alignItems: "center",
    }}>
      <span style={{ fontSize: 11, color: "#b5a99a" }}>${cost.total_usd.toFixed(6)}</span>
      <span style={{ fontSize: 11, color: "#c4bfb8" }}>{cost.calls} calls</span>
    </div>
  );
}
