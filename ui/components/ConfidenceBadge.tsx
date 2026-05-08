"use client";

interface ConfidenceBadgeProps {
  confidence: "high" | "medium" | "low" | string;
}

const CONFIG: Record<string, { bg: string; color: string; border: string }> = {
  high: {
    bg: "rgba(0,255,135,0.08)",
    color: "#00c968",
    border: "rgba(0,255,135,0.2)",
  },
  medium: {
    bg: "rgba(255,215,0,0.08)",
    color: "#ffd700",
    border: "rgba(255,215,0,0.2)",
  },
  low: {
    bg: "rgba(107,107,126,0.12)",
    color: "#8888a0",
    border: "rgba(107,107,126,0.25)",
  },
};

export default function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const key = confidence.toLowerCase();
  const style = CONFIG[key] ?? CONFIG.low;

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
        backgroundColor: style.bg,
        color: style.color,
        border: `1px solid ${style.border}`,
      }}
    >
      {confidence.toUpperCase()}
    </span>
  );
}
