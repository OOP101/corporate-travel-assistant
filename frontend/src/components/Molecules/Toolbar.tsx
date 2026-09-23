import { ReactNode } from 'react';
import { Search } from 'lucide-react';

export const Toolbar = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={`flex items-center gap-2.5 flex-wrap ${className || ''}`}>{children}</div>
);

export interface SearchInputProps {
  value: string;
  onChange: (v: string) => void;
  onEnter?: () => void;
  placeholder?: string;
  className?: string;
}

/** 带放大镜的搜索框，回车触发检索 */
export const SearchInput = ({ value, onChange, onEnter, placeholder, className }: SearchInputProps) => (
  <div className={`relative ${className || ''}`}>
    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none" />
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && onEnter) onEnter();
      }}
      placeholder={placeholder || '搜索'}
      className="w-full pl-9 pr-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white text-ink-900 placeholder:text-ink-400 focusable"
    />
  </div>
);

export interface FilterSelectProps {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  className?: string;
}

/** 轻量筛选下拉，用于列表页顶部 */
export const FilterSelect = ({ value, onChange, options, className }: FilterSelectProps) => (
  <select
    value={value}
    onChange={(e) => onChange(e.target.value)}
    className={`px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white text-ink-600 focusable cursor-pointer ${className || ''}`}
  >
    {options.map((o) => (
      <option key={o.value} value={o.value}>
        {o.label}
      </option>
    ))}
  </select>
);
