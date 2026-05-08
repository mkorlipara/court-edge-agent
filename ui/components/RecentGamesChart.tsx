"use client";

import { useEffect, useState } from "react";
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  ReferenceLine,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { formatMarketShort } from "@/lib/utils";

interface GameLog {
  game_date: string;
  matchup: string;
  value: number;
}

interface ChartRow extends GameLog {
  trend: number;
}

interface RecentGamesChartProps {
  playerName: string;
  market: string;
  beforeDate: string;
  propLine?: number | null;
}

function shortDate(dateStr: string): string {
  const [, month, day] = dateStr.split("-");
  return `${parseInt(month)}/${parseInt(day)}`;
}

function shortMatchup(matchup: string): string {
  if (matchup.includes("vs.")) return matchup.split("vs.")[1]?.trim() ?? matchup;
  if (matchup.includes("@")) {
    const parts = matchup.split("@");
    return `@${parts[1]?.trim() ?? ""}`;
  }
  // ESPN format: "@ ATL" or "vs ATL"
  return matchup.trim();
}

interface CustomXTickProps {
  x?: number;
  y?: number;
  payload?: { value: string };
  data: ChartRow[];
}

function CustomXTick({ x = 0, y = 0, payload, data }: CustomXTickProps) {
  const dateStr = payload?.value ?? "";
  const row = data.find((d) => d.game_date === dateStr);
  const opp = row ? shortMatchup(row.matchup) : "";
  const date = shortDate(dateStr);

  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={0} dy={14} textAnchor="middle" fill="#6b6b7e" fontSize={11}>
        {date}
      </text>
      <text x={0} y={0} dy={26} textAnchor="middle" fill="#4a4a5a" fontSize={10}>
        {opp}
      </text>
    </g>
  );
}

/** Simple ordinary-least-squares linear regression — returns per-index trend values. */
function linearTrend(values: number[]): number[] {
  const n = values.length;
  if (n < 2) return [...values];
  const xMean = (n - 1) / 2;
  const yMean = values.reduce((a, b) => a + b, 0) / n;
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMean) * (values[i] - yMean);
    den += (i - xMean) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = yMean - slope * xMean;
  return values.map((_, i) => parseFloat((slope * i + intercept).toFixed(2)));
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; dataKey: string; payload: ChartRow }>;
  propLine?: number | null;
  market: string;
}

function CustomTooltip({ active, payload, propLine, market }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const barPayload = payload.find((p) => p.dataKey === "value");
  if (!barPayload) return null;
  const d = barPayload.payload;
  const val = barPayload.value;
  const hit = propLine == null || val >= propLine;

  return (
    <div
      style={{
        backgroundColor: "#1a1a22",
        border: "1px solid #252530",
        borderRadius: "6px",
        padding: "8px 12px",
        fontSize: "12px",
        lineHeight: "1.6",
        pointerEvents: "none",
      }}
    >
      <div style={{ color: "#6b6b7e", marginBottom: "2px" }}>
        {d.game_date} · {shortMatchup(d.matchup)}
      </div>
      <div
        style={{
          fontWeight: 700,
          fontSize: "15px",
          color: hit ? "#00ff87" : "#ff6b35",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {val.toFixed(1)}{" "}
        <span style={{ fontSize: "11px", fontWeight: 500, color: "#6b6b7e" }}>
          {formatMarketShort(market)}
        </span>
      </div>
      {propLine != null && (
        <div style={{ fontSize: "11px", color: "#6b6b7e" }}>
          {hit
            ? `+${(val - propLine).toFixed(1)} over line`
            : `${(val - propLine).toFixed(1)} under line`}
        </div>
      )}
    </div>
  );
}

export default function RecentGamesChart({
  playerName,
  market,
  beforeDate,
  propLine,
}: RecentGamesChartProps) {
  const [games, setGames] = useState<ChartRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(false);

    const params = new URLSearchParams({
      market,
      limit: "5",
      ...(beforeDate ? { before_date: beforeDate } : {}),
    });

    fetch(
      `http://localhost:8000/player/${encodeURIComponent(playerName)}/history?${params}`
    )
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then((data) => {
        const raw: GameLog[] = data.games ?? [];
        const trend = linearTrend(raw.map((g) => g.value));
        setGames(raw.map((g, i) => ({ ...g, trend: trend[i] })));
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  }, [playerName, market, beforeDate]);

  const allValues = games.flatMap((g) => [g.value, g.trend]);
  const yMax =
    allValues.length > 0
      ? Math.ceil(Math.max(...allValues, propLine ?? 0) * 1.2)
      : 40;

  return (
    <div style={{ padding: "16px 20px", borderTop: "1px solid #252530" }}>
      {/* Header */}
      <div
        style={{
          fontSize: "11px",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "#6b6b7e",
          fontWeight: 600,
          marginBottom: "14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span>Last 5 Games · {formatMarketShort(market)}</span>
        {propLine != null && (
          <span
            style={{
              color: "#4a4a5a",
              fontWeight: 500,
              textTransform: "none",
              letterSpacing: 0,
              fontSize: "11px",
            }}
          >
            Line: {propLine}
          </span>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div
          style={{
            height: "140px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div style={{ display: "flex", gap: "4px" }}>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  width: "4px",
                  height: "4px",
                  borderRadius: "50%",
                  backgroundColor: "#252530",
                  animation: `dot-pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                }}
              />
            ))}
          </div>
        </div>
      )}

      {/* Error / empty */}
      {!loading && (error || games.length === 0) && (
        <div
          style={{
            height: "140px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span style={{ fontSize: "12px", color: "#4a4a5a" }}>
            {error ? "No history available" : "No games found"}
          </span>
        </div>
      )}

      {/* Chart */}
      {!loading && !error && games.length > 0 && (
        <>
          <ResponsiveContainer width="100%" height={168}>
            <ComposedChart
              data={games}
              margin={{ top: 6, right: 6, bottom: 16, left: -20 }}
              barCategoryGap="28%"
            >
              <XAxis
                dataKey="game_date"
                tick={<CustomXTick data={games} />}
                axisLine={{ stroke: "#1a1a22" }}
                tickLine={false}
                height={42}
              />
              <YAxis
                domain={[0, yMax]}
                tick={{ fill: "#4a4a5a", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={36}
              />
              <Tooltip
                content={<CustomTooltip propLine={propLine} market={market} />}
                cursor={{ fill: "rgba(255,255,255,0.03)" }}
              />

              {/* Prop line reference */}
              {propLine != null && (
                <ReferenceLine
                  y={propLine}
                  stroke="#3a3a4a"
                  strokeDasharray="4 3"
                  strokeWidth={1.5}
                  label={{
                    value: propLine.toString(),
                    position: "insideTopRight",
                    fill: "#4a4a5a",
                    fontSize: 10,
                    dy: -4,
                  }}
                />
              )}

              {/* Bars */}
              <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={44}>
                {games.map((entry, i) => {
                  const over = propLine == null || entry.value >= propLine;
                  return (
                    <Cell
                      key={i}
                      fill={over ? "rgba(0,255,135,0.45)" : "rgba(255,107,53,0.45)"}
                      stroke={over ? "#00ff87" : "#ff6b35"}
                      strokeWidth={1}
                    />
                  );
                })}
              </Bar>

              {/* Trend line */}
              <Line
                dataKey="trend"
                stroke="#a5b4fc"
                strokeWidth={2}
                dot={false}
                strokeDasharray="0"
                type="linear"
                legendType="none"
                activeDot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>

          {/* Trend legend */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              marginTop: "8px",
            }}
          >
            <div
              style={{
                width: "16px",
                height: "2px",
                backgroundColor: "#a5b4fc",
                borderRadius: "1px",
              }}
            />
            <span style={{ fontSize: "10px", color: "#4a4a5a" }}>Trend</span>
            {propLine != null && (
              <>
                <div
                  style={{
                    width: "16px",
                    height: "2px",
                    backgroundColor: "#3a3a4a",
                    borderRadius: "1px",
                    marginLeft: "8px",
                    borderTop: "1px dashed #3a3a4a",
                  }}
                />
                <span style={{ fontSize: "10px", color: "#4a4a5a" }}>Line</span>
              </>
            )}
          </div>
        </>
      )}

      <style>{`
        @keyframes dot-pulse {
          0%, 80%, 100% { opacity: 0.2; transform: scale(1); }
          40% { opacity: 1; transform: scale(1.4); }
        }
      `}</style>
    </div>
  );
}
