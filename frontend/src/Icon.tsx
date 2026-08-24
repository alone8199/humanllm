import { CSSProperties } from "react";

type IconProps = {
  size?: number;
  className?: string;
  style?: CSSProperties;
  strokeWidth?: number;
};

// 统一线性图标风格（Lucide 风格，stroke 跟随 currentColor）
function base(size: number, strokeWidth: number, className?: string, style?: CSSProperties) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    style,
  };
}

// 请调用我 品牌图标：聊天气泡（微信风格，双气泡对话）
export function LogoIcon({ size = 26, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      {/* 左侧气泡（发出） */}
      <path d="M21 11.5a8.38 8.38 0 0 1-9 8.3 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-4.1A8.38 8.38 0 0 1 12 3a8.5 8.5 0 0 1 9 8.5z" />
      {/* 右侧小气泡（接收） */}
      <path d="M21 4v4a3 3 0 0 1-3 3H9l-2.5 2.5V11a3 3 0 0 1-3-3V4a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3z" opacity="0.55" />
    </svg>
  );
}

export function OverviewIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  );
}

export function WorkbenchIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <path d="M21 11.5a8.38 8.38 0 0 1-9 8.3 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-4.1A8.38 8.38 0 0 1 12 3a8.5 8.5 0 0 1 9 8.5z" />
    </svg>
  );
}

export function UsersIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="3.2" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.9" />
      <path d="M16 3.1a4 4 0 0 1 0 7.8" />
    </svg>
  );
}

export function ModelsIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1" />
    </svg>
  );
}

export function KeyIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="M10.7 12.3 21 2M16 7l3 3M14 9l2 2" />
    </svg>
  );
}

export function TasksIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  );
}

export function UsageIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <path d="M3 3v18h18" />
      <path d="M7 14l3-4 3 3 4-6" />
    </svg>
  );
}

export function LogsIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <path d="M4 4h16v16H4z" />
      <path d="M8 9h8M8 13h8M8 17h5" />
    </svg>
  );
}

export function LogoutIcon({ size = 18, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  );
}

export function SunIcon({ size = 16, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

export function MoonIcon({ size = 16, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}

export function AutoIcon({ size = 16, className, style, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth, className, style)} aria-hidden="true">
      <rect x="3" y="4" width="18" height="14" rx="2" />
      <path d="M8 21h8M12 18v3" />
    </svg>
  );
}
