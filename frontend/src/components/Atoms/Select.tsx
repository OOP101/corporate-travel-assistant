import { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

export interface SelectProps {
  options: Array<{ value: string; label: string }>;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  style?: React.CSSProperties;
  label?: string;
}

export const Select = ({
  options,
  value,
  onChange,
  placeholder,
  disabled,
  className,
  style,
  label,
}: SelectProps) => {
  return (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-[13px] font-medium text-ink-600">{label}</label>
      )}
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className={`block w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable appearance-none pr-8 disabled:bg-gray-50 disabled:text-gray-400 ${className || ''}`}
          style={style}
        >
          {placeholder && <option value="" disabled>{placeholder}</option>}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
      </div>
      {options.length === 0 && (
        <p className="text-xs text-gray-400">无可用选项</p>
      )}
    </div>
  );
};
