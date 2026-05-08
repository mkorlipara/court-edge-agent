"use client";

import { RefreshCw } from "lucide-react";
import LeanBadge from "./LeanBadge";
import ConfidenceBadge from "./ConfidenceBadge";
import SourceBadge from "./SourceBadge";
import RecentGamesChart from "./RecentGamesChart";
import { formatMarket, formatDate } from "@/lib/utils";

export interface PredictResult {
  player_name: string;
  game_date: string;
  market: string;
  projection: number;
  prop_line?: number | null;
  edge?: number | null;
  lean?: string | null;
  confidence: string;
  explanation: string[];
  source: string;
}

interface ResultCardProps {
  result: PredictResult;
  onReset: () => void;
}

export default function ResultCard({ result, onReset }: ResultCardProps) {
  const hasPropLine = result.prop_line != null;
  const hasEdge = result.edge != null && hasPropLine;
  const edgePositive = (result.edge ?? 0) >= 0;

  return (
    <div
      style={{
        backgroundColor: "#131318",
        border: "1px solid #252530",
        borderRadius: "12px",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Card header */}
      <div
        style={{
          borderBottom: "1px solid #252530",
          padding: "16px 20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "#f0f0f5" }}>
            {result.player_name}
          </div>
          <div style={{ fontSize: "12px", color: "#6b6b7e", marginTop: "2px" }}>
            {formatMarket(result.market)} · {formatDate(result.game_date)}
          </div>
        </div>
        <button
          onClick={onReset}
          title="New prediction"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "7px 12px",
            borderRadius: "6px",
            border: "1px solid #252530",
            backgroundColor: "transparent",
            color: "#6b6b7e",
            fontSize: "12px",
            fontWeight: 500,
            cursor: "pointer",
            transition: "all 0.15s ease",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#363645";
            (e.currentTarget as HTMLButtonElement).style.color = "#f0f0f5";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#252530";
            (e.currentTarget as HTMLButtonElement).style.color = "#6b6b7e";
          }}
        >
          <RefreshCw size={12} />
          New
        </button>
      </div>

      {/* Projection hero */}
      <div
        style={{
          padding: "32px 20px 24px",
          textAlign: "center",
          borderBottom: "1px solid #252530",
        }}
      >
        <div
          style={{
            fontSize: "72px",
            fontWeight: 900,
            lineHeight: 1,
            letterSpacing: "-0.03em",
            color: "#f0f0f5",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {result.projection.toFixed(1)}
        </div>
        <div style={{ fontSize: "12px", color: "#6b6b7e", marginTop: "8px", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 500 }}>
          Projected {formatMarket(result.market)}
        </div>

        {hasPropLine && (
          <div style={{ marginTop: "16px", display: "flex", alignItems: "center", justifyContent: "center", gap: "12px" }}>
            <span style={{ fontSize: "13px", color: "#6b6b7e" }}>
              Line <span style={{ color: "#8888a0", fontWeight: 600 }}>{result.prop_line}</span>
            </span>
            {hasEdge && (
              <>
                <span style={{ color: "#252530" }}>·</span>
                <span
                  style={{
                    fontSize: "15px",
                    fontWeight: 700,
                    color: edgePositive ? "#00ff87" : "#ff6b35",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {edgePositive ? "+" : ""}{result.edge!.toFixed(1)}
                </span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Lean + Confidence */}
      <div
        style={{
          padding: "16px 20px",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          borderBottom: "1px solid #252530",
          flexWrap: "wrap",
        }}
      >
        {result.lean && hasPropLine && <LeanBadge lean={result.lean} />}
        <ConfidenceBadge confidence={result.confidence} />
        <span style={{ marginLeft: "auto" }}>
          <SourceBadge source={result.source} />
        </span>
      </div>

      {/* Explanation */}
      {result.explanation && result.explanation.length > 0 && (
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #252530" }}>
          <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", color: "#6b6b7e", fontWeight: 600, marginBottom: "10px" }}>
            Analysis
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {result.explanation.slice(0, 3).map((line, i) => (
              <p key={i} style={{ fontSize: "13px", lineHeight: "1.6", color: "#9090a8", margin: 0 }}>
                {line}
              </p>
            ))}
          </div>
        </div>
      )}

      {/* Recent games chart */}
      <RecentGamesChart
        playerName={result.player_name}
        market={result.market}
        beforeDate={String(result.game_date)}
        propLine={result.prop_line}
      />
    </div>
  );
}
