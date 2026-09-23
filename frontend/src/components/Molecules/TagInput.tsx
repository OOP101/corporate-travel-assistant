import { useState } from 'react';
import { X } from 'lucide-react';

export interface TagInputProps {
  value?: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

/** 标签输入：回车添加、点 × 删除、退格删除末项 */
export const TagInput = ({ value = [], onChange, placeholder = '输入后回车添加' }: TagInputProps) => {
  const [draft, setDraft] = useState('');

  const add = () => {
    const t = draft.trim();
    if (!t) return;
    if (!value.includes(t)) onChange([...value, t]);
    setDraft('');
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-2 min-h-[38px] focus-within:border-primary-400 focus-within:ring-2 focus-within:ring-primary-100 transition-all">
      {value.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 text-xs border border-primary-100"
        >
          {t}
          <button
            type="button"
            onClick={() => onChange(value.filter((x) => x !== t))}
            className="hover:text-primary-900 transition-colors"
          >
            <X size={11} />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            add();
          }
          if (e.key === 'Backspace' && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={add}
        placeholder={value.length ? '' : placeholder}
        className="flex-1 min-w-[90px] bg-transparent text-[13px] text-ink-900 focus:outline-none py-0.5 placeholder:text-ink-400"
      />
    </div>
  );
};
