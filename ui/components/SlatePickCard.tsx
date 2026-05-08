"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import LeanBadge from "./LeanBadge";
import ConfidenceBadge from "./ConfidenceBadge";
import { formatMarketShort } from "@/lib/utils";

export interface SlatePick {
  rank: number;
  player_name: string;
  team: string;
  opponent: string;
  home_away: string;
  market: string;
  prop_line: number;
  hgb_projection: number;
  llm_projection?: number | null;
  edge: number;
  lean: string;
  confidence: string;
  explanation: string[];
}

interface SlatePickCardProps {
  pick: SlatePick;
}

export default function SlatePickCard({ pick }: SlatePickCardProps) {
  const [expanded, setExpanded] = useState(false);
  const edgePositive = pick.edge >= 0;
  const vsLabel = pick.home_away === "HOME"
    ? `${pick.team} vs ${pick.opponent}`
    : `${pick.team} @ ${pick.opponent}`;

  return (
    <div
      style={{
        backgroundColor: "#131318",
        border: "1px solid #252530",
        borderRadius: "10px",
        overflow: "hidden",
        transition: "border-color 0.15s ease",
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLDivElement).style.borderColor = "#2e2e3e")}
      onMouseLeave={(e) => ((e.currentTarget as HTMLDivElement).style.borderColor = "#252530")}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "44px 1fr auto",
          alignItems: "center",
          gap: "0",
          padding: "0",
        }}
      >
        {/* Rank */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            alignSelf: "stretch",
            borderRight: "1px solid #1a1a22",
            backgroundColor: "#0f0f14",
          }}
        >
          <span
            style={{
              fontSize: "18px",
              fontWeight: 800,
              color: pick.rank <= 3 ? "#2e2e3a" : "#1e1e28",
              letterSpacing: "-0.02em",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {pick.rank}
          </span>
        </div>

        {/* Main content */}
        <div style={{ padding: "14px 16px", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginBottom: "6px" }}>
            <span style={{ fontSize: "15px", fontWeight: 700, color: "#f0f0f5", whiteSpace: "nowrap" }}>
              {pick.player_name}
            </span>
            <span style={{ fontSize: "12px", color: "#6b6b7e", whiteSpace: "nowrap" }}>
              · {vsLabel}
            </span>
            {/* Market pill */}
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                padding: "2px 7px",
                borderRadius: "4px",
                fontSize: "10px",
                fontWeight: 700,
                letterSpacing: "0.06em",
                backgroundColor: "#1a1a22",
                color: "#8888a0",
                border: "1px solid #252530",
                whiteSpace: "nowrap",
              }}
            >
              {formatMarketShort(pick.market)}
            </span>
          </div>

          {/* Projection + edge row */}
          <div style={{ display: "flex", alignItems: "baseline", gap: "10px", flexWrap: "wrap" }}>
            <span
              style={{
                fontSize: "28px",
                fontWeight: 900,
                color: "#f0f0f5",
                letterSpacing: "-0.02em",
                lineHeight: 1,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {pick.llm_projection != null
                ? pick.llm_projection.toFixed(1)
                : pick.hgb_projection.toFixed(1)}
            </span>
            <span style={{ fontSize: "12px", color: "#6b6b7e" }}>
              line <span style={{ color: "#8888a0", fontWeight: 600 }}>{pick.prop_line}</span>
            </span>
            <span
              style={{
                fontSize: "15px",
                fontWeight: 700,
                color: edgePositive ? "#00ff87" : "#ff6b35",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {edgePositive ? "+" : ""}{pick.edge.toFixed(1)}
            </span>
            {pick.hgb_projection != null && (
              <span style={{ fontSize: "11px", color: "#4a4a5a", marginLeft: "2px" }}>
                Model anchor: {pick.hgb_projection.toFixed(1)}
              </span>
            )}
          </div>
        </div>

        {/* Right badges column */}
        <div
          style={{
            padding: "14px 16px",
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: "6px",
            flexShrink: 0,
          }}
        >
          <LeanBadge lean={pick.lean} />
          <ConfidenceBadge confidence={pick.confidence} />
        </div>
      </div>

      {/* Expandable explanation */}
      {pick.explanation && pick.explanation.length > 0 && (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 16px 8px 60px",
              backgroundColor: "transparent",
              border: "none",
              borderTop: "1px solid #1a1a22",
              cursor: "pointer",
              color: "#4a4a5a",
              fontSize: "11px",
              fontWeight: 500,
              fontFamily: "inherit",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              transition: "color 0.15s ease",
            }}
            onMouseEnter={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#6b6b7e")}
            onMouseLeave={(e) => ((e.currentTarget as HTMLButtonElement).style.color = "#4a4a5a")}
          >
            Analysis
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>

          {expanded && (
            <div
              style={{
                padding: "12px 16px 16px 60px",
                display: "flex",
                flexDirection: "column",
                gap: "7px",
                borderTop: "1px solid #1a1a22",
              }}
            >
              {pick.explanation.map((line, i) => (
                <p
                  key={i}
                  style={{
                    fontSize: "13px",
                    lineHeight: "1.6",
                    color: "#9090a8",
                    margin: 0,
                  }}
                >
                  {line}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
