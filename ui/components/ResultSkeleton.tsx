"use client";

function Bone({ width = "100%", height = "16px", borderRadius = "4px" }: {
  width?: string;
  height?: string;
  borderRadius?: string;
}) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius,
        backgroundColor: "#1a1a22",
        animation: "skeleton-pulse 1.5s ease-in-out infinite",
      }}
    />
  );
}

export default function ResultSkeleton() {
  return (
    <div
      style={{
        backgroundColor: "#131318",
        border: "1px solid #252530",
        borderRadius: "12px",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{ borderBottom: "1px solid #252530", padding: "16px 20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <Bone width="140px" height="16px" />
          <Bone width="100px" height="11px" />
        </div>
        <Bone width="52px" height="30px" borderRadius="6px" />
      </div>

      {/* Hero projection */}
      <div style={{ padding: "32px 20px 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: "12px", borderBottom: "1px solid #252530" }}>
        <Bone width="120px" height="72px" borderRadius="8px" />
        <Bone width="90px" height="12px" />
        <Bone width="140px" height="16px" />
      </div>

      {/* Badges */}
      <div style={{ padding: "16px 20px", display: "flex", gap: "8px", borderBottom: "1px solid #252530" }}>
        <Bone width="60px" height="26px" borderRadius="9999px" />
        <Bone width="72px" height="26px" borderRadius="9999px" />
      </div>

      {/* Explanation */}
      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: "8px" }}>
        <Bone width="60px" height="11px" />
        <Bone width="100%" height="13px" />
        <Bone width="85%" height="13px" />
        <Bone width="70%" height="13px" />
      </div>

      <style>{`
        @keyframes skeleton-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
