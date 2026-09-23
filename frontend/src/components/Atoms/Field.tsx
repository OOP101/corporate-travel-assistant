import { ReactNode } from 'react';

export interface FieldProps {
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

/** 表单字段容器：统一标签排版与必填标记 */
export const Field = ({ label, hint, required, children, className }: FieldProps) => (
  <div className={className || ''}>
    <div className="text-[12px] font-medium text-ink-600 mb-1.5">
      {label}
      {required && <span className="text-red-500 ml-0.5">*</span>}
    </div>
    {children}
    {hint && <div className="text-[11px] text-ink-400 mt-1">{hint}</div>}
  </div>
);
