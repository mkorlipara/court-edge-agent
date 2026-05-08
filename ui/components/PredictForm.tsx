"use client";

import { useState } from "react";
import { Loader2, TrendingUp } from "lucide-react";
import { todayISODate } from "@/lib/utils";

interface FormState {
  player_name: string;
  game_date: string;
  market: string;
  opponent: string;
  home_away: "HOME" | "AWAY";
  prop_line: string;
}

interface PredictFormProps {
  onResult: (result: unknown) => void;
  onError: (msg: string) => void;
  onLoading: (loading: boolean) => void;
  loading: boolean;
}

const MARKETS = [
  { value: "points", label: "Points" },
  { value: "rebounds", label: "Rebounds" },
  { value: "assists", label: "Assists" },
  { value: "threes_made", label: "3-Pointers Made" },
];

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "11px",
  fontWeight: 600,
  color: "#6b6b7e",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  marginBottom: "6px",
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

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
  backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%236b6b7e' d='M6 8L1 3h10z'/%3E%3C/svg%3E")`,
  backgroundRepeat: "no-repeat",
  backgroundPosition: "right 12px center",
  paddingRight: "32px",
  appearance: "none" as const,
  WebkitAppearance: "none" as const,
};

function InputField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label style={labelStyle}>{label}</label>
      {children}
    </div>
  );
}

export default function PredictForm({ onResult, onError, onLoading, loading }: PredictFormProps) {
  const [form, setForm] = useState<FormState>({
    player_name: "",
    game_date: todayISODate(),
    market: "points",
    opponent: "",
    home_away: "HOME",
    prop_line: "",
  });

  const [focusedField, setFocusedField] = useState<string | null>(null);

  function update(field: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function getFocusStyle(field: string): React.CSSProperties {
    return focusedField === field
      ? { borderColor: "#00ff87", boxShadow: "0 0 0 1px rgba(0,255,135,0.15)" }
      : {};
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.player_name.trim() || !form.opponent.trim()) {
      onError("Player name and opponent are required.");
      return;
    }

    onLoading(true);
    onError("");
    onResult(null);

    const body: Record<string, unknown> = {
      player_name: form.player_name.trim(),
      game_date: form.game_date,
      market: form.market,
      opponent: form.opponent.trim().toUpperCase(),
      home_away: form.home_away,
    };

    if (form.prop_line !== "") {
      const parsed = parseFloat(form.prop_line);
      if (!isNaN(parsed)) {
        body.prop_line = parsed;
      }
    }

    try {
      const res = await fetch("http://localhost:8000/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }

      const data = await res.json();
      onResult(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Request failed";
      onError(msg);
    } finally {
      onLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>

        <InputField label="Player Name">
          <input
            type="text"
            placeholder="Jalen Brunson"
            value={form.player_name}
            onChange={(e) => update("player_name", e.target.value)}
            onFocus={() => setFocusedField("player_name")}
            onBlur={() => setFocusedField(null)}
            style={{ ...inputStyle, ...getFocusStyle("player_name") }}
            autoComplete="off"
          />
        </InputField>

        <div className="form-grid-2">
          <InputField label="Game Date">
            <input
              type="date"
              value={form.game_date}
              onChange={(e) => update("game_date", e.target.value)}
              onFocus={() => setFocusedField("game_date")}
              onBlur={() => setFocusedField(null)}
              style={{ ...inputStyle, ...getFocusStyle("game_date"), colorScheme: "dark" }}
            />
          </InputField>

          <InputField label="Market">
            <select
              value={form.market}
              onChange={(e) => update("market", e.target.value)}
              onFocus={() => setFocusedField("market")}
              onBlur={() => setFocusedField(null)}
              style={{ ...selectStyle, ...getFocusStyle("market") }}
            >
              {MARKETS.map((m) => (
                <option key={m.value} value={m.value} style={{ backgroundColor: "#131318" }}>
                  {m.label}
                </option>
              ))}
            </select>
          </InputField>
        </div>

        <div className="form-grid-2">
          <InputField label="Opponent">
            <input
              type="text"
              placeholder="BOS"
              value={form.opponent}
              onChange={(e) => update("opponent", e.target.value.toUpperCase())}
              onFocus={() => setFocusedField("opponent")}
              onBlur={() => setFocusedField(null)}
              style={{ ...inputStyle, ...getFocusStyle("opponent"), textTransform: "uppercase" }}
              maxLength={3}
              autoComplete="off"
            />
          </InputField>

          <InputField label="Prop Line">
            <input
              type="number"
              placeholder="27.5"
              value={form.prop_line}
              onChange={(e) => update("prop_line", e.target.value)}
              onFocus={() => setFocusedField("prop_line")}
              onBlur={() => setFocusedField(null)}
              style={{ ...inputStyle, ...getFocusStyle("prop_line") }}
              step="0.5"
              min="0"
            />
          </InputField>
        </div>

        {/* Home / Away toggle */}
        <InputField label="Location">
          <div style={{ display: "flex", border: "1px solid #252530", borderRadius: "6px", overflow: "hidden" }}>
            {(["HOME", "AWAY"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => update("home_away", option)}
                style={{
                  flex: 1,
                  padding: "10px 0",
                  fontSize: "13px",
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                  letterSpacing: "0.04em",
                  backgroundColor: form.home_away === option ? "rgba(0,255,135,0.12)" : "transparent",
                  color: form.home_away === option ? "#00ff87" : "#6b6b7e",
                  borderRight: option === "HOME" ? "1px solid #252530" : "none",
                  fontFamily: "inherit",
                }}
              >
                {option}
              </button>
            ))}
          </div>
        </InputField>

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%",
            padding: "13px",
            borderRadius: "8px",
            border: "none",
            backgroundColor: loading ? "rgba(0,255,135,0.15)" : "#00ff87",
            color: loading ? "#00ff87" : "#0d0d0f",
            fontSize: "14px",
            fontWeight: 700,
            cursor: loading ? "not-allowed" : "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px",
            marginTop: "4px",
            transition: "all 0.15s ease",
            letterSpacing: "0.02em",
            fontFamily: "inherit",
          }}
          onMouseEnter={(e) => {
            if (!loading) {
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = "#00e87a";
            }
          }}
          onMouseLeave={(e) => {
            if (!loading) {
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = "#00ff87";
            }
          }}
        >
          {loading ? (
            <>
              <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />
              Projecting...
            </>
          ) : (
            <>
              <TrendingUp size={15} />
              Get Projection
            </>
          )}
        </button>
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </form>
  );
}
