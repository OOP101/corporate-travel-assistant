import { ReactNode } from 'react';

export interface InputProps {
  type?: string;
  placeholder?: string;
  value: string | number;
  onChange: (value: string | number) => void;
  disabled?: boolean;
  label?: string;
  className?: string;
  style?: React.CSSProperties;
  error?: string;
  errorMessage?: string;
}

export const Input = ({
  type = 'text',
  placeholder,
  value,
  onChange,
  disabled,
  label,
  className,
  style,
  error,
  errorMessage,
}: InputProps) => {
  return (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-[13px] font-medium text-ink-600">{label}</label>
      )}
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={`block w-full px-3 py-2 text-sm bg-white border rounded-lg focusable ${
          error ? 'border-red-400' : 'border-gray-200'
        } disabled:bg-gray-50 disabled:text-gray-400 ${className || ''}`}
        style={style}
        aria-invalid={!!error}
      />
      {error && (
        <p className="text-xs text-red-600">{errorMessage || error}</p>
      )}
    </div>
  );
};
