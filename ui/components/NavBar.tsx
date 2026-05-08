"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Predict" },
  { href: "/slate", label: "Slate" },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <header
      style={{
        borderBottom: "1px solid #1a1a22",
        padding: "0 24px",
        display: "flex",
        alignItems: "center",
        height: "52px",
        gap: "0",
        position: "sticky",
        top: 0,
        backgroundColor: "#0d0d0f",
        zIndex: 50,
      }}
    >
      {/* Brand */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginRight: "32px" }}>
        <Activity size={15} style={{ color: "#00ff87", flexShrink: 0 }} />
        <span
          style={{
            fontSize: "13px",
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "#f0f0f5",
            whiteSpace: "nowrap",
          }}
        >
          Court Edge
        </span>
      </div>

      {/* Nav links */}
      <nav style={{ display: "flex", alignItems: "center", gap: "2px" }}>
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                padding: "5px 12px",
                borderRadius: "6px",
                fontSize: "13px",
                fontWeight: isActive ? 600 : 400,
                color: isActive ? "#f0f0f5" : "#6b6b7e",
                backgroundColor: isActive ? "#1a1a22" : "transparent",
                textDecoration: "none",
                transition: "all 0.15s ease",
                letterSpacing: "0.01em",
              }}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
