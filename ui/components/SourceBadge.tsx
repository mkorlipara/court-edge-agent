"use client";

interface SourceBadgeProps {
  source: string;
}

export default function SourceBadge({ source }: SourceBadgeProps) {
  const isLLM = source === "llm";

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "3px 9px",
        borderRadius: "9999px",
        fontSize: "11px",
        fontWeight: 600,
        letterSpacing: "0.03em",
        backgroundColor: isLLM ? "rgba(129,140,248,0.1)" : "rgba(107,107,126,0.1)",
        color: isLLM ? "#a5b4fc" : "#6b6b7e",
        border: `1px solid ${isLLM ? "rgba(129,140,248,0.2)" : "rgba(107,107,126,0.2)"}`,
      }}
    >
      {isLLM ? "GPT-4o" : "Model fallback"}
    </span>
  );
}
