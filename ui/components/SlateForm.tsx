"use client";

import { useState } from "react";
import { BarChart2 } from "lucide-react";
import { todayISODate } from "@/lib/utils";

const MARKET_OPTIONS = [
  { value: "points", label: "Points" },
  { value: "rebounds", label: "Rebounds" },
  { value: "assists", label: "Assists" },
  { value: "threes_made", label: "3-Pointers Made" },
];

interface SlateFormProps {
  onSubmit: (params: SlateParams) => void;
  loading: boolean;
}

export interface SlateParams {
  game_date: string;
  markets: string[];
  min_edge: number;
  top_n: number;
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "11px",
  fontWeight: 600,
  color: "#6b6b7e",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  marginBottom: "7px",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  backgroundColor: "#0d0d0f",
  color: "#f0f0f5",
  border: "1px solid #252530",
  borderRadius: "6px",
  padding: "10px 12px",
  fontSize: "14px",
  outline: "none",
  transition: "border-color 0.15s ease",
  fontFamily: "inherit",
};

export default function SlateForm({ onSubmit, loading }: SlateFormProps) {
  const [date, setDate] = useState(todayISODate());
  const [markets, setMarkets] = useState<string[]>(["points", "rebounds", "assists", "threes_made"]);
  const [minEdge, setMinEdge] = useState("1.5");
  const [topN, setTopN] = useState("10");
  const [focusedField, setFocusedField] = useState<string | null>(null);

  function toggleMarket(value: string) {
    setMarkets((prev) =>
      prev.includes(value) ? prev.filter((m) => m !== value) : [...prev, value]
    );
  }

  function getFocus(field: string): React.CSSProperties {
    return focusedField === field
      ? { borderColor: "#00ff87", boxShadow: "0 0 0 1px rgba(0,255,135,0.15)" }
      : {};
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (markets.length === 0) return;
    onSubmit({
      game_date: date,
      markets,
      min_edge: parseFloat(minEdge) || 1.5,
      top_n: parseInt(topN) || 10,
    });
  }

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
        {/* Date + thresholds row */}
        <div className="form-grid-2">
          <div>
            <label style={labelStyle}>Game Date</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              onFocus={() => setFocusedField("date")}
              onBlur={() => setFocusedField(null)}
              style={{ ...inputStyle, ...getFocus("date"), colorScheme: "dark" }}
            />
          </div>
          <div className="form-grid-2" style={{ gap: "8px" }}>
            <div>
              <label style={labelStyle}>Min Edge</label>
              <input
                type="number"
                value={minEdge}
                onChange={(e) => setMinEdge(e.target.value)}
                onFocus={() => setFocusedField("minEdge")}
                onBlur={() => setFocusedField(null)}
                style={{ ...inputStyle, ...getFocus("minEdge") }}
                step="0.5"
                min="0"
              />
            </div>
            <div>
              <label style={labelStyle}>Top N</label>
              <input
                type="number"
                value={topN}
                onChange={(e) => setTopN(e.target.value)}
                onFocus={() => setFocusedField("topN")}
                onBlur={() => setFocusedField(null)}
                style={{ ...inputStyle, ...getFocus("topN") }}
                min="1"
                max="25"
              />
            </div>
          </div>
        </div>

        {/* Markets multi-select */}
        <div>
          <label style={labelStyle}>Markets</label>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {MARKET_OPTIONS.map((m) => {
              const checked = markets.includes(m.value);
              return (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => toggleMarket(m.value)}
                  style={{
                    padding: "7px 13px",
                    borderRadius: "6px",
                    border: `1px solid ${checked ? "rgba(0,255,135,0.35)" : "#252530"}`,
                    backgroundColor: checked ? "rgba(0,255,135,0.1)" : "transparent",
                    color: checked ? "#00ff87" : "#6b6b7e",
                    fontSize: "13px",
                    fontWeight: checked ? 600 : 400,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                    fontFamily: "inherit",
                    whiteSpace: "nowrap",
                  }}
                >
                  {m.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={loading || markets.length === 0}
          style={{
            width: "100%",
            padding: "13px",
            borderRadius: "8px",
            border: "none",
            backgroundColor: loading || markets.length === 0 ? "rgba(0,255,135,0.15)" : "#00ff87",
            color: loading || markets.length === 0 ? "#00ff87" : "#0d0d0f",
            fontSize: "14px",
            fontWeight: 700,
            cursor: loading || markets.length === 0 ? "not-allowed" : "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px",
            transition: "all 0.15s ease",
            letterSpacing: "0.02em",
            fontFamily: "inherit",
          }}
          onMouseEnter={(e) => {
            if (!loading && markets.length > 0)
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = "#00e87a";
          }}
          onMouseLeave={(e) => {
            if (!loading && markets.length > 0)
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = "#00ff87";
          }}
        >
          <BarChart2 size={15} />
          Analyze Slate
        </button>
      </div>
    </form>
  );
}
