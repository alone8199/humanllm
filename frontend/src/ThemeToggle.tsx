import { useEffect, useState } from "react";
import { SunIcon, MoonIcon, AutoIcon } from "./Icon";

type ThemeMode = "light" | "dark" | "auto";

const KEY = "humanllm-theme";

function applyTheme(mode: ThemeMode) {
  const root = document.documentElement;
  if (mode === "auto") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", mode);
  }
  localStorage.setItem(KEY, mode);
}

function initialTheme(): ThemeMode {
  const saved = localStorage.getItem(KEY) as ThemeMode | null;
  return saved === "light" || saved === "dark" || saved === "auto" ? saved : "light";
}

export default function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>(initialTheme());

  useEffect(() => {
    applyTheme(mode);
  }, [mode]);

  const opts: [ThemeMode, JSX.Element][] = [
    ["light", <SunIcon />],
    ["dark", <MoonIcon />],
    ["auto", <AutoIcon />],
  ];

  return (
    <div className="theme-toggle" role="group" aria-label="主题">
      {opts.map(([m, icon]) => (
        <button
          key={m}
          className={mode === m ? "active" : ""}
          onClick={() => setMode(m)}
          title={m === "light" ? "亮色" : m === "dark" ? "暗色" : "跟随系统"}
          aria-label={m === "light" ? "亮色" : m === "dark" ? "暗色" : "跟随系统"}
        >
          {icon}
        </button>
      ))}
    </div>
  );
}
