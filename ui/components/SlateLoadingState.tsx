"use client";

import { useEffect, useState } from "react";

const STAGES = [
  { label: "Fetching today's slate...", duration: 2500 },
  { label: "Loading player game logs...", duration: 3000 },
  { label: "Scoring candidates against lines...", duration: 4000 },
  { label: "Running edge calculations...", duration: 3500 },
  { label: "Enriching top picks with context...", duration: 0 },
];

export default function SlateLoadingState() {
  const [stageIndex, setStageIndex] = useState(0);
  const [dotCount, setDotCount] = useState(1);

  useEffect(() => {
    let elapsed = 0;
    const timers: ReturnType<typeof setTimeout>[] = [];

    STAGES.forEach((stage, i) => {
      if (i === 0) return;
      elapsed += STAGES[i - 1].duration;
      if (elapsed > 0) {
        const t = setTimeout(() => {
          setStageIndex(i);
        }, elapsed);
        timers.push(t);
      }
    });

    return () => timers.forEach(clearTimeout);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setDotCount((d) => (d % 3) + 1);
    }, 400);
    return () => clearInterval(interval);
  }, []);

  const dots = ".".repeat(dotCount);

  return (
    <div
      style={{
        backgroundColor: "#131318",
        border: "1px solid #252530",
        borderRadius: "12px",
        padding: "40px 32px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "28px",
      }}
    >
      {/* Pulsing orb */}
      <div style={{ position: "relative", width: "52px", height: "52px" }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: "50%",
            backgroundColor: "rgba(0,255,135,0.08)",
            animation: "slate-ping 1.5s cubic-bezier(0,0,0.2,1) infinite",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: "8px",
            borderRadius: "50%",
            backgroundColor: "rgba(0,255,135,0.15)",
            animation: "slate-ping 1.5s cubic-bezier(0,0,0.2,1) infinite 0.3s",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: "16px",
            borderRadius: "50%",
            backgroundColor: "#00ff87",
          }}
        />
      </div>

      {/* Stage list */}
      <div style={{ display: "flex", flexDirection: "column", gap: "10px", width: "100%", maxWidth: "320px" }}>
        {STAGES.map((stage, i) => {
          const isDone = i < stageIndex;
          const isActive = i === stageIndex;
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
                opacity: isDone ? 0.35 : isActive ? 1 : 0.2,
                transition: "opacity 0.4s ease",
              }}
            >
              {/* Status dot */}
              <div
                style={{
                  width: "6px",
                  height: "6px",
                  borderRadius: "50%",
                  flexShrink: 0,
                  backgroundColor: isDone ? "#00c968" : isActive ? "#00ff87" : "#252530",
                  transition: "background-color 0.3s ease",
                  boxShadow: isActive ? "0 0 6px rgba(0,255,135,0.6)" : "none",
                }}
              />
              <span
                style={{
                  fontSize: "13px",
                  color: isDone ? "#4a4a5a" : isActive ? "#c8c8d8" : "#3a3a4a",
                  fontVariantNumeric: "tabular-nums",
                  transition: "color 0.3s ease",
                }}
              >
                {isActive ? `${stage.label.replace(/\.\.\.$/, "")}${dots}` : stage.label}
              </span>
            </div>
          );
        })}
      </div>

      <p style={{ fontSize: "12px", color: "#4a4a5a", margin: 0 }}>
        This usually takes 10–20 seconds
      </p>

      <style>{`
        @keyframes slate-ping {
          75%, 100% { transform: scale(2); opacity: 0; }
        }
      `}</style>
    </div>
  );
}
