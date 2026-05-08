"use client";

import { useState } from "react";
import { AlertCircle, Calendar, Users, TrendingUp } from "lucide-react";
import SlateForm, { type SlateParams } from "@/components/SlateForm";
import SlatePickCard, { type SlatePick } from "@/components/SlatePickCard";
import SlateLoadingState from "@/components/SlateLoadingState";
import { formatDate } from "@/lib/utils";

interface SlateResult {
  date: string;
  games_on_slate: number;
  candidates_evaluated: number;
  edges_above_threshold: number;
  top_picks: SlatePick[];
}

const EMPTY_MESSAGES: Record<string, string> = {
  "No NBA games scheduled": "No NBA games scheduled for this date.",
  "No prop lines": "No prop lines found for this date. Run scripts/fetch_odds.py first.",
};

function matchEmptyState(detail: string): string | null {
  for (const [key, msg] of Object.entries(EMPTY_MESSAGES)) {
    if (detail.toLowerCase().includes(key.toLowerCase())) return msg;
  }
  return null;
}

export default function SlatePage() {
  const [result, setResult] = useState<SlateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [emptyState, setEmptyState] = useState<string>("");
  const [lastParams, setLastParams] = useState<SlateParams | null>(null);

  async function handleSubmit(params: SlateParams) {
    setLoading(true);
    setError("");
    setEmptyState("");
    setResult(null);
    setLastParams(params);

    try {
      const res = await fetch("http://localhost:8000/slate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        const detail = err.detail ?? `HTTP ${res.status}`;
        const emptyMsg = matchEmptyState(detail);
        if (emptyMsg) {
          setEmptyState(emptyMsg);
        } else {
          setError(detail);
        }
        return;
      }

      const data: SlateResult = await res.json();

      if (!data.top_picks || data.top_picks.length === 0) {
        setEmptyState(`No edges above ${params.min_edge} found for this slate.`);
        return;
      }

      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        maxWidth: "760px",
        margin: "0 auto",
        padding: "40px 24px 80px",
      }}
    >
      {/* Page header */}
      <div style={{ marginBottom: "28px" }}>
        <h1
          style={{
            fontSize: "28px",
            fontWeight: 800,
            color: "#f0f0f5",
            letterSpacing: "-0.02em",
            lineHeight: 1.2,
            margin: "0 0 8px",
          }}
        >
          Slate Analysis
        </h1>
        <p style={{ fontSize: "14px", color: "#6b6b7e", margin: 0 }}>
          Score every candidate on today's slate and surface the sharpest edges
        </p>
      </div>

      {/* Form card */}
      <div
        style={{
          backgroundColor: "#131318",
          border: "1px solid #252530",
          borderRadius: "12px",
          padding: "20px",
          marginBottom: "28px",
        }}
      >
        <SlateForm onSubmit={handleSubmit} loading={loading} />
      </div>

      {/* Error banner */}
      {error && (
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
            padding: "12px 16px",
            borderRadius: "8px",
            border: "1px solid rgba(255,77,77,0.3)",
            backgroundColor: "rgba(255,77,77,0.08)",
            marginBottom: "20px",
            color: "#ff6b6b",
            fontSize: "13px",
            lineHeight: "1.5",
          }}
        >
          <AlertCircle size={15} style={{ flexShrink: 0, marginTop: "1px" }} />
          <span>{error}</span>
        </div>
      )}

      {/* Loading state */}
      {loading && <SlateLoadingState />}

      {/* Empty state */}
      {!loading && emptyState && (
        <div
          style={{
            backgroundColor: "#131318",
            border: "1px solid #252530",
            borderRadius: "12px",
            padding: "48px 32px",
            textAlign: "center",
          }}
        >
          <div
            style={{
              width: "40px",
              height: "40px",
              borderRadius: "50%",
              backgroundColor: "#1a1a22",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 16px",
            }}
          >
            <Calendar size={18} style={{ color: "#4a4a5a" }} />
          </div>
          <p style={{ fontSize: "14px", color: "#6b6b7e", margin: 0 }}>{emptyState}</p>
        </div>
      )}

      {/* Results */}
      {!loading && result && (
        <>
          {/* Summary bar */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0",
              backgroundColor: "#131318",
              border: "1px solid #252530",
              borderRadius: "10px",
              overflow: "hidden",
              marginBottom: "16px",
            }}
          >
            {[
              { icon: <Calendar size={13} />, value: result.games_on_slate, label: "games" },
              { icon: <Users size={13} />, value: result.candidates_evaluated, label: "candidates" },
              { icon: <TrendingUp size={13} />, value: result.edges_above_threshold, label: `edges ≥ ${lastParams?.min_edge ?? 1.5}` },
            ].map((item, i) => (
              <div
                key={i}
                style={{
                  flex: 1,
                  padding: "12px 16px",
                  borderRight: i < 2 ? "1px solid #1a1a22" : "none",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: "3px",
                }}
              >
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 800,
                    color: "#f0f0f5",
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "-0.02em",
                  }}
                >
                  {item.value}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "4px", color: "#6b6b7e" }}>
                  {item.icon}
                  <span style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 500 }}>
                    {item.label}
                  </span>
                </div>
              </div>
            ))}
            <div
              style={{
                padding: "12px 20px",
                borderLeft: "1px solid #1a1a22",
                fontSize: "12px",
                color: "#4a4a5a",
                whiteSpace: "nowrap",
                alignSelf: "center",
              }}
            >
              {formatDate(result.date)}
            </div>
          </div>

          {/* Pick cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {result.top_picks.map((pick) => (
              <SlatePickCard key={`${pick.rank}-${pick.player_name}-${pick.market}`} pick={pick} />
            ))}
          </div>
        </>
      )}
    </main>
  );
}
