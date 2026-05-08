"use client";

interface LeanBadgeProps {
  lean: "over" | "under" | string;
}

export default function LeanBadge({ lean }: LeanBadgeProps) {
  const isOver = lean.toLowerCase() === "over";

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "4px 12px",
        borderRadius: "9999px",
        fontSize: "11px",
        fontWeight: 700,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        backgroundColor: isOver ? "rgba(0,255,135,0.12)" : "rgba(255,107,53,0.12)",
        color: isOver ? "#00ff87" : "#ff6b35",
        border: `1px solid ${isOver ? "rgba(0,255,135,0.3)" : "rgba(255,107,53,0.3)"}`,
      }}
    >
      {lean.toUpperCase()}
    </span>
  );
}
