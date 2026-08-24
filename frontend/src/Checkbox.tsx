import React from "react";

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: React.ReactNode;
  disabled?: boolean;
  className?: string;
}

export function Checkbox({ checked, onChange, label, disabled, className = "" }: CheckboxProps) {
  return (
    <label className={`checkbox-row ${className} ${disabled ? "disabled" : ""}`}>
      <input
        type="checkbox"
        className="checkbox-input"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="checkbox-box" aria-hidden="true" />
      {label && <span className="checkbox-text">{label}</span>}
    </label>
  );
}
