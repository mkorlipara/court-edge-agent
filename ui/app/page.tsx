"use client";

import { useState } from "react";
import { AlertCircle } from "lucide-react";
import PredictForm from "@/components/PredictForm";
import ResultCard, { type PredictResult } from "@/components/ResultCard";
import ResultSkeleton from "@/components/ResultSkeleton";

export default function Home() {
  const [result, setResult] = useState<PredictResult | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const hasResult = result !== null;
  const showResultPane = loading || hasResult;

  function handleReset() {
    setResult(null);
    setError("");
    setLoading(false);
  }

  return (
    <main
      style={{
        maxWidth: showResultPane ? "960px" : "480px",
        margin: "0 auto",
        padding: "40px 24px 80px",
        transition: "max-width 0.3s ease",
      }}
    >
      {!showResultPane && (
        <div style={{ marginBottom: "32px" }}>
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
            Get a Projection
          </h1>
          <p style={{ fontSize: "14px", color: "#6b6b7e", margin: 0 }}>
            Live context AI + HGB model fallback
          </p>
        </div>
      )}

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

      <div
        className={showResultPane ? "result-layout" : undefined}
        style={{
          display: showResultPane ? "grid" : "block",
          gridTemplateColumns: showResultPane ? "minmax(320px, 400px) 1fr" : undefined,
          gap: showResultPane ? "32px" : undefined,
          alignItems: "start",
        }}
      >
        <div
          style={{
            backgroundColor: "#131318",
            border: "1px solid #252530",
            borderRadius: "12px",
            padding: "20px",
          }}
        >
          {showResultPane && (
            <div style={{ marginBottom: "16px", paddingBottom: "16px", borderBottom: "1px solid #252530" }}>
              <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.07em", color: "#6b6b7e", fontWeight: 600 }}>
                Prediction
              </div>
            </div>
          )}
          <PredictForm
            onResult={(data) => setResult(data as PredictResult)}
            onError={setError}
            onLoading={setLoading}
            loading={loading}
          />
        </div>

        {showResultPane && (
          <div>
            {loading ? (
              <ResultSkeleton />
            ) : result ? (
              <ResultCard result={result} onReset={handleReset} />
            ) : null}
          </div>
        )}
      </div>
    </main>
  );
}
