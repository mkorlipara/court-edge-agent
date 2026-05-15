"use client";

import { useEffect, useState, useCallback } from "react";
import {
  RefreshCw,
  AlertCircle,
  Zap,
  ChevronUp,
  ChevronDown,
  Minus,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface TodayGame {
  home_team: string;
  away_team: string;
  game_time: string | null;
}

interface TodayLine {
  player_name: string;
  team: string | null;
  opponent: string | null;
  home_away: "HOME" | "AWAY" | null;
  market: "points" | "rebounds" | "assists" | "threes_made";
  line: number;
  over_odds: number | null;
  under_odds: number | null;
  bookmaker: string;
  projection: number | null;
  edge: number | null;
  lean: "over" | "under" | null;
}

interface TodayResponse {
  date: string;
  games: TodayGame[];
  top_edges: TodayLine[];
  all_lines: TodayLine[];
  total_lines: number;
  scored_lines: number;
  fetched_at: string;
  odds_api_available: boolean;
  from_cache: boolean;
  note: string | null;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const MARKET_LABELS: Record<string, string> = {
  points: "PTS",
  rebounds: "REB",
  assists: "AST",
  threes_made: "3PM",
};

const MARKET_FILTERS = [
  { value: "all", label: "All" },
  { value: "points", label: "PTS" },
  { value: "rebounds", label: "REB" },
  { value: "assists", label: "AST" },
  { value: "threes_made", label: "3PM" },
];

// ─── Helper components ────────────────────────────────────────────────────────

function formatOdds(n: number | null): string {
  if (n === null) return "—";
  return n > 0 ? `+${n}` : `${n}`;
}

function EdgePill({ edge, lean }: { edge: number | null; lean: "over" | "under" | null }) {
  if (edge === null || lean === null) return null;
  const abs = Math.abs(edge);
  const isOver = lean === "over";

  let bg = "rgba(255,255,255,0.06)";
  let color = "#8b8b9e";
  if (abs >= 3) {
    bg = isOver ? "rgba(0,255,135,0.12)" : "rgba(255,77,77,0.12)";
    color = isOver ? "#00e87a" : "#ff5a5a";
  } else if (abs >= 1.5) {
    bg = isOver ? "rgba(0,200,100,0.08)" : "rgba(255,100,100,0.08)";
    color = isOver ? "#00c864" : "#ff7070";
  }

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "3px",
        padding: "2px 8px",
        borderRadius: "4px",
        backgroundColor: bg,
        color,
        fontSize: "12px",
        fontWeight: 700,
        fontVariantNumeric: "tabular-nums",
        letterSpacing: "-0.01em",
        whiteSpace: "nowrap",
      }}
    >
      {isOver ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
      {isOver ? "+" : ""}
      {edge.toFixed(1)}
    </span>
  );
}

function MarketBadge({ market }: { market: string }) {
  return (
    <span
      style={{
        fontSize: "10px",
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "#4a4a5a",
        backgroundColor: "#1a1a22",
        padding: "2px 6px",
        borderRadius: "3px",
      }}
    >
      {MARKET_LABELS[market] ?? market}
    </span>
  );
}

function SkeletonRow() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "12px",
        padding: "14px 16px",
        borderBottom: "1px solid #1a1a22",
      }}
    >
      <div style={{ flex: 1 }}>
        <div
          style={{
            height: "13px",
            width: "140px",
            borderRadius: "4px",
            backgroundColor: "#1a1a22",
            marginBottom: "6px",
            animation: "pulse 1.5s infinite",
          }}
        />
        <div
          style={{
            height: "11px",
            width: "80px",
            borderRadius: "4px",
            backgroundColor: "#131318",
            animation: "pulse 1.5s infinite",
          }}
        />
      </div>
      <div
        style={{
          height: "22px",
          width: "48px",
          borderRadius: "4px",
          backgroundColor: "#1a1a22",
          animation: "pulse 1.5s infinite",
        }}
      />
      <div
        style={{
          height: "22px",
          width: "56px",
          borderRadius: "4px",
          backgroundColor: "#131318",
          animation: "pulse 1.5s infinite",
        }}
      />
    </div>
  );
}

function GameChip({ game }: { game: TodayGame }) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        padding: "6px 12px",
        backgroundColor: "#131318",
        border: "1px solid #252530",
        borderRadius: "8px",
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      <span style={{ fontSize: "13px", fontWeight: 700, color: "#f0f0f5" }}>
        {game.away_team}
      </span>
      <span style={{ fontSize: "10px", color: "#4a4a5a", fontWeight: 500 }}>@</span>
      <span style={{ fontSize: "13px", fontWeight: 700, color: "#f0f0f5" }}>
        {game.home_team}
      </span>
    </div>
  );
}

function LineRow({ line }: { line: TodayLine }) {
  const hasEdge = line.edge !== null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto auto auto",
        alignItems: "center",
        gap: "12px",
        padding: "11px 16px",
        borderBottom: "1px solid #131318",
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLDivElement).style.background = "#131318")}
      onMouseLeave={(e) => ((e.currentTarget as HTMLDivElement).style.background = "transparent")}
    >
      {/* Player + context */}
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: "13px",
            fontWeight: 600,
            color: "#e8e8f0",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {line.player_name}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            marginTop: "2px",
            flexWrap: "wrap",
          }}
        >
          <MarketBadge market={line.market} />
          {line.team && line.opponent && (
            <span style={{ fontSize: "11px", color: "#4a4a5a" }}>
              {line.team} vs {line.opponent}
            </span>
          )}
        </div>
      </div>

      {/* Line */}
      <div style={{ textAlign: "right" }}>
        <div
          style={{
            fontSize: "15px",
            fontWeight: 800,
            color: "#f0f0f5",
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.02em",
          }}
        >
          {line.line}
        </div>
        <div style={{ fontSize: "10px", color: "#4a4a5a", marginTop: "1px" }}>
          {line.bookmaker}
        </div>
      </div>

      {/* Projection */}
      <div style={{ textAlign: "right", minWidth: "52px" }}>
        {hasEdge ? (
          <>
            <div
              style={{
                fontSize: "13px",
                fontWeight: 700,
                color: "#8b8b9e",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {line.projection}
            </div>
            <div style={{ fontSize: "10px", color: "#4a4a5a" }}>proj</div>
          </>
        ) : (
          <Minus size={13} style={{ color: "#3a3a4a" }} />
        )}
      </div>

      {/* Edge pill */}
      <div style={{ minWidth: "60px", display: "flex", justifyContent: "flex-end" }}>
        {hasEdge ? (
          <EdgePill edge={line.edge!} lean={line.lean!} />
        ) : (
          <span style={{ fontSize: "11px", color: "#3a3a4a" }}>—</span>
        )}
      </div>
    </div>
  );
}

// ─── Top Edge Card ────────────────────────────────────────────────────────────

function TopEdgeCard({ line, rank, date }: { line: TodayLine; rank: number; date: string }) {
  const abs = Math.abs(line.edge ?? 0);
  const isOver = line.lean === "over";
  const isHigh = abs >= 3;
  const isMed = abs >= 1.5 && abs < 3;

  const accentColor = isHigh
    ? isOver
      ? "#00e87a"
      : "#ff5a5a"
    : isMed
    ? isOver
      ? "#00c864"
      : "#ff7070"
    : "#8b8b9e";

  return (
    <div
      style={{
        backgroundColor: "#131318",
        border: `1px solid ${isHigh ? (isOver ? "rgba(0,232,122,0.2)" : "rgba(255,90,90,0.2)") : "#252530"}`,
        borderRadius: "10px",
        padding: "14px 16px",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Rank accent */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "3px",
          height: "100%",
          backgroundColor: accentColor,
          borderRadius: "10px 0 0 10px",
        }}
      />

      <div style={{ paddingLeft: "8px" }}>
        {/* Header row */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: "8px",
            marginBottom: "8px",
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontSize: "14px",
                fontWeight: 700,
                color: "#f0f0f5",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {line.player_name}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                marginTop: "3px",
                flexWrap: "wrap",
              }}
            >
              <MarketBadge market={line.market} />
              {(() => {
                const dateLabel = new Date(date + "T12:00:00").toLocaleDateString("en-US", {
                  month: "short", day: "numeric",
                });
                if (line.team && line.opponent) {
                  const matchup = line.home_away === "HOME"
                    ? `${line.opponent} @ ${line.team}`
                    : `${line.team} @ ${line.opponent}`;
                  return (
                    <span style={{ fontSize: "11px", color: "#6b6b7e" }}>
                      {matchup} · {dateLabel}
                    </span>
                  );
                }
                if (line.team) {
                  return (
                    <span style={{ fontSize: "11px", color: "#6b6b7e" }}>
                      {line.team} · {dateLabel}
                    </span>
                  );
                }
                return (
                  <span style={{ fontSize: "11px", color: "#6b6b7e" }}>
                    {dateLabel}
                  </span>
                );
              })()}
            </div>
          </div>
          <div
            style={{
              fontSize: "11px",
              fontWeight: 700,
              color: "#3a3a4a",
              letterSpacing: "0.04em",
              flexShrink: 0,
            }}
          >
            #{rank}
          </div>
        </div>

        {/* Stats row */}
        <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
          <div>
            <span style={{ fontSize: "11px", color: "#4a4a5a" }}>Line </span>
            <span
              style={{
                fontSize: "18px",
                fontWeight: 800,
                color: "#f0f0f5",
                fontVariantNumeric: "tabular-nums",
                letterSpacing: "-0.02em",
              }}
            >
              {line.line}
            </span>
          </div>
          <div style={{ color: "#252530", fontSize: "18px", fontWeight: 200 }}>·</div>
          <div>
            <span style={{ fontSize: "11px", color: "#4a4a5a" }}>Proj </span>
            <span
              style={{
                fontSize: "18px",
                fontWeight: 800,
                color: accentColor,
                fontVariantNumeric: "tabular-nums",
                letterSpacing: "-0.02em",
              }}
            >
              {line.projection}
            </span>
          </div>
          <div style={{ color: "#252530", fontSize: "18px", fontWeight: 200 }}>·</div>
          <EdgePill edge={line.edge} lean={line.lean} />
        </div>

        {/* Odds row */}
        {(line.over_odds !== null || line.under_odds !== null) && (
          <div
            style={{
              display: "flex",
              gap: "10px",
              marginTop: "8px",
              fontSize: "11px",
              color: "#4a4a5a",
            }}
          >
            <span>
              Over {formatOdds(line.over_odds)}{" "}
              {isOver && <span style={{ color: accentColor }}>←</span>}
            </span>
            <span>/</span>
            <span>
              Under {formatOdds(line.under_odds)}{" "}
              {!isOver && <span style={{ color: accentColor }}>←</span>}
            </span>
            <span style={{ marginLeft: "4px", color: "#3a3a4a" }}>via {line.bookmaker}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

function localDateIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function TodayPage() {
  const todayIso = localDateIso();

  const [data, setData] = useState<TodayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [marketFilter, setMarketFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [selectedDate, setSelectedDate] = useState(todayIso);
  const [edgePage, setEdgePage] = useState(0);
  const [linesPage, setLinesPage] = useState(0);
  const EDGES_PER_PAGE = 3;
  const LINES_PER_PAGE = 5;

  const load = useCallback(async (date: string, skipCache = false) => {
    setError("");
    try {
      const params = new URLSearchParams({ date });
      if (skipCache) params.set("skip_cache", "true");
      const res = await fetch(`http://localhost:8000/today?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const json: TodayResponse = await res.json();
      setData(json);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load today's data");
    }
  }, []);

  // On mount: find the next date with actual games, then load it
  useEffect(() => {
    async function init() {
      setLoading(true);
      try {
        const res = await fetch("http://localhost:8000/next-slate-date");
        if (res.ok) {
          const { date: nextDate } = await res.json();
          if (nextDate && nextDate !== selectedDate) {
            setSelectedDate(nextDate); // triggers the load effect below
            return;
          }
        }
      } catch {
        // fall through to load with default date
      }
      await load(selectedDate, false);
      setLoading(false);
    }
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once on mount only

  // Reload whenever selectedDate changes (after initial mount resolves it)
  useEffect(() => {
    setLoading(true);
    setData(null);
    setEdgePage(0);
    setLinesPage(0);
    load(selectedDate, false).finally(() => setLoading(false));
  }, [load, selectedDate]);

  async function handleRefresh() {
    setRefreshing(true);
    await load(selectedDate, true);
    setRefreshing(false);
  }

  // Filtered lines — reset page whenever filters change
  const filteredLines = (data?.all_lines ?? []).filter((l) => {
    if (marketFilter !== "all" && l.market !== marketFilter) return false;
    if (search && !l.player_name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const totalLinesPages = Math.ceil(filteredLines.length / LINES_PER_PAGE);
  const pagedLines = filteredLines.slice(linesPage * LINES_PER_PAGE, linesPage * LINES_PER_PAGE + LINES_PER_PAGE);

  const formattedDate = data?.date
    ? new Date(data.date + "T12:00:00").toLocaleDateString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
      })
    : "";

  return (
    <>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>

      <main style={{ maxWidth: "820px", margin: "0 auto", padding: "32px 24px 80px" }}>
        {/* ── Page header ── */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            marginBottom: "24px",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          <div>
            <h1
              style={{
                fontSize: "26px",
                fontWeight: 800,
                color: "#f0f0f5",
                letterSpacing: "-0.02em",
                margin: "0 0 4px",
              }}
            >
              Today
            </h1>
            <p style={{ fontSize: "13px", color: "#4a4a5a", margin: 0 }}>
              {loading ? "Loading slate…" : formattedDate || "NBA slate"}
            </p>
          </div>

          {/* Date picker + status chips + refresh */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => e.target.value && setSelectedDate(e.target.value)}
              style={{
                padding: "4px 8px",
                borderRadius: "6px",
                border: "1px solid #252530",
                backgroundColor: "#131318",
                color: "#8b8b9e",
                fontSize: "12px",
                outline: "none",
                cursor: "pointer",
              }}
            />
            {data?.from_cache && (
              <span
                style={{
                  fontSize: "11px",
                  color: "#4a4a5a",
                  backgroundColor: "#131318",
                  border: "1px solid #252530",
                  borderRadius: "5px",
                  padding: "3px 8px",
                }}
              >
                cached
              </span>
            )}
            {data && (
              <span
                style={{
                  fontSize: "11px",
                  color: "#4a4a5a",
                  backgroundColor: "#131318",
                  border: "1px solid #252530",
                  borderRadius: "5px",
                  padding: "3px 8px",
                }}
              >
                {data.scored_lines}/{data.total_lines} scored
              </span>
            )}
            <button
              onClick={handleRefresh}
              disabled={loading || refreshing}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "5px",
                padding: "5px 10px",
                borderRadius: "6px",
                border: "1px solid #252530",
                backgroundColor: "#131318",
                color: "#6b6b7e",
                fontSize: "12px",
                cursor: loading || refreshing ? "not-allowed" : "pointer",
                opacity: loading || refreshing ? 0.5 : 1,
              }}
            >
              <RefreshCw
                size={12}
                style={{
                  animation: refreshing ? "spin 1s linear infinite" : "none",
                }}
              />
              Refresh
            </button>
          </div>
        </div>

        {/* ── Error banner ── */}
        {error && (
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: "10px",
              padding: "12px 16px",
              borderRadius: "8px",
              border: "1px solid rgba(255,77,77,0.3)",
              backgroundColor: "rgba(255,77,77,0.06)",
              marginBottom: "20px",
              color: "#ff6b6b",
              fontSize: "13px",
            }}
          >
            <AlertCircle size={14} style={{ flexShrink: 0, marginTop: "1px" }} />
            <span>{error}</span>
          </div>
        )}

        {/* ── Note banner ── */}
        {!loading && data?.note && (
          <div
            style={{
              padding: "10px 14px",
              borderRadius: "7px",
              border: "1px solid #252530",
              backgroundColor: "#131318",
              marginBottom: "20px",
              color: "#6b6b7e",
              fontSize: "12px",
              lineHeight: 1.5,
            }}
          >
            {data.note}
          </div>
        )}

        {/* ── Games strip ── */}
        {(loading || (data?.games?.length ?? 0) > 0) && (
          <section style={{ marginBottom: "28px" }}>
            <h2
              style={{
                fontSize: "11px",
                fontWeight: 700,
                color: "#4a4a5a",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                margin: "0 0 10px",
              }}
            >
              Games
            </h2>
            <div
              style={{
                display: "flex",
                gap: "8px",
                overflowX: "auto",
                paddingBottom: "4px",
                scrollbarWidth: "none",
              }}
            >
              {loading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <div
                      key={i}
                      style={{
                        height: "34px",
                        width: "120px",
                        borderRadius: "8px",
                        backgroundColor: "#131318",
                        flexShrink: 0,
                        animation: "pulse 1.5s infinite",
                      }}
                    />
                  ))
                : data?.games.map((g, i) => <GameChip key={i} game={g} />)}
            </div>
          </section>
        )}

        {/* ── Best Edges ── */}
        <section style={{ marginBottom: "32px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "12px",
            }}
          >
            <Zap size={13} style={{ color: "#00e87a" }} />
            <h2
              style={{
                fontSize: "11px",
                fontWeight: 700,
                color: "#4a4a5a",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                margin: 0,
              }}
            >
              Best Edges
            </h2>
          </div>

          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  style={{
                    height: "90px",
                    borderRadius: "10px",
                    backgroundColor: "#131318",
                    animation: "pulse 1.5s infinite",
                  }}
                />
              ))}
            </div>
          ) : data?.top_edges && data.top_edges.length > 0 ? (
            (() => {
              const totalEdges = data.top_edges.length;
              const totalPages = Math.ceil(totalEdges / EDGES_PER_PAGE);
              const pageEdges = data.top_edges.slice(
                edgePage * EDGES_PER_PAGE,
                edgePage * EDGES_PER_PAGE + EDGES_PER_PAGE,
              );
              const globalOffset = edgePage * EDGES_PER_PAGE;
              return (
                <div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {pageEdges.map((line, i) => (
                      <TopEdgeCard
                        key={`${line.player_name}-${line.market}`}
                        line={line}
                        rank={globalOffset + i + 1}
                        date={data.date}
                      />
                    ))}
                  </div>

                  {/* Pagination controls */}
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginTop: "12px",
                      padding: "0 2px",
                    }}
                  >
                    <button
                      onClick={() => setEdgePage((p) => Math.max(0, p - 1))}
                      disabled={edgePage === 0}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: "5px 12px",
                        borderRadius: "6px",
                        border: "1px solid #252530",
                        backgroundColor: "transparent",
                        color: edgePage === 0 ? "#2a2a38" : "#6b6b7e",
                        fontSize: "12px",
                        cursor: edgePage === 0 ? "not-allowed" : "pointer",
                      }}
                    >
                      <ChevronDown size={12} style={{ transform: "rotate(90deg)" }} />
                      Prev
                    </button>

                    <span style={{ fontSize: "11px", color: "#3a3a4a" }}>
                      {globalOffset + 1}–{Math.min(globalOffset + EDGES_PER_PAGE, totalEdges)} of {totalEdges}
                    </span>

                    <button
                      onClick={() => setEdgePage((p) => Math.min(totalPages - 1, p + 1))}
                      disabled={edgePage >= totalPages - 1}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: "5px 12px",
                        borderRadius: "6px",
                        border: "1px solid #252530",
                        backgroundColor: "transparent",
                        color: edgePage >= totalPages - 1 ? "#2a2a38" : "#6b6b7e",
                        fontSize: "12px",
                        cursor: edgePage >= totalPages - 1 ? "not-allowed" : "pointer",
                      }}
                    >
                      Next
                      <ChevronDown size={12} style={{ transform: "rotate(-90deg)" }} />
                    </button>
                  </div>
                </div>
              );
            })()
          ) : !loading && !error ? (
            <div
              style={{
                padding: "24px",
                textAlign: "center",
                backgroundColor: "#131318",
                border: "1px solid #1a1a22",
                borderRadius: "10px",
                color: "#3a3a4a",
                fontSize: "13px",
              }}
            >
              {data?.odds_api_available
                ? "No scored edges yet — run scripts/ingest_player_logs.py to add player data"
                : "Add ODDS_API_KEY to .env to see live edges"}
            </div>
          ) : null}
        </section>

        {/* ── All Lines ── */}
        <section>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "12px",
              gap: "12px",
              flexWrap: "wrap",
            }}
          >
            <h2
              style={{
                fontSize: "11px",
                fontWeight: 700,
                color: "#4a4a5a",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                margin: 0,
              }}
            >
              All Lines
              {data && (
                <span style={{ color: "#3a3a4a", fontWeight: 500, marginLeft: "6px" }}>
                  ({filteredLines.length})
                </span>
              )}
            </h2>

            {/* Controls */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              {/* Search */}
              <input
                type="text"
                placeholder="Search player…"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setLinesPage(0); }}
                style={{
                  padding: "5px 10px",
                  borderRadius: "6px",
                  border: "1px solid #252530",
                  backgroundColor: "#131318",
                  color: "#e8e8f0",
                  fontSize: "12px",
                  outline: "none",
                  width: "140px",
                }}
              />

              {/* Market filter pills */}
              <div style={{ display: "flex", gap: "4px" }}>
                {MARKET_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    onClick={() => { setMarketFilter(f.value); setLinesPage(0); }}
                    style={{
                      padding: "4px 9px",
                      borderRadius: "5px",
                      border: "1px solid",
                      borderColor: marketFilter === f.value ? "#4a4a8a" : "#252530",
                      backgroundColor: marketFilter === f.value ? "#1e1e2e" : "transparent",
                      color: marketFilter === f.value ? "#a0a0d0" : "#4a4a5a",
                      fontSize: "11px",
                      fontWeight: 600,
                      cursor: "pointer",
                      letterSpacing: "0.04em",
                    }}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div
            style={{
              backgroundColor: "#0f0f13",
              border: "1px solid #1a1a22",
              borderRadius: "10px",
              overflow: "hidden",
            }}
          >
            {/* Table header */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto auto auto",
                gap: "12px",
                padding: "8px 16px",
                borderBottom: "1px solid #1a1a22",
              }}
            >
              {["Player", "Line", "Proj", "Edge"].map((col) => (
                <div
                  key={col}
                  style={{
                    fontSize: "10px",
                    fontWeight: 700,
                    color: "#3a3a4a",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    textAlign: col !== "Player" ? "right" : "left",
                  }}
                >
                  {col}
                </div>
              ))}
            </div>

            {/* Rows */}
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
            ) : pagedLines.length > 0 ? (
              pagedLines.map((line) => (
                <LineRow key={`${line.player_name}-${line.market}`} line={line} />
              ))
            ) : (
              <div
                style={{
                  padding: "40px",
                  textAlign: "center",
                  color: "#3a3a4a",
                  fontSize: "13px",
                }}
              >
                {data?.total_lines === 0
                  ? "No prop lines available for today"
                  : "No lines match your filters"}
              </div>
            )}
          </div>

          {/* Lines pagination */}
          {!loading && filteredLines.length > LINES_PER_PAGE && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginTop: "10px",
                padding: "0 2px",
              }}
            >
              <button
                onClick={() => setLinesPage((p) => Math.max(0, p - 1))}
                disabled={linesPage === 0}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                  padding: "5px 12px",
                  borderRadius: "6px",
                  border: "1px solid #252530",
                  backgroundColor: "transparent",
                  color: linesPage === 0 ? "#2a2a38" : "#6b6b7e",
                  fontSize: "12px",
                  cursor: linesPage === 0 ? "not-allowed" : "pointer",
                }}
              >
                <ChevronDown size={12} style={{ transform: "rotate(90deg)" }} />
                Prev
              </button>
              <span style={{ fontSize: "11px", color: "#3a3a4a" }}>
                {linesPage * LINES_PER_PAGE + 1}–{Math.min((linesPage + 1) * LINES_PER_PAGE, filteredLines.length)} of {filteredLines.length}
              </span>
              <button
                onClick={() => setLinesPage((p) => Math.min(totalLinesPages - 1, p + 1))}
                disabled={linesPage >= totalLinesPages - 1}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                  padding: "5px 12px",
                  borderRadius: "6px",
                  border: "1px solid #252530",
                  backgroundColor: "transparent",
                  color: linesPage >= totalLinesPages - 1 ? "#2a2a38" : "#6b6b7e",
                  fontSize: "12px",
                  cursor: linesPage >= totalLinesPages - 1 ? "not-allowed" : "pointer",
                }}
              >
                Next
                <ChevronDown size={12} style={{ transform: "rotate(-90deg)" }} />
              </button>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
