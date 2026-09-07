import { ReactNode } from 'react';

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
}

export const PageHeader = ({ title, subtitle, actions, className }: PageHeaderProps) => (
  <div className={`flex items-center justify-between mb-5 ${className || ''}`}>
    <div>
      <h1 className="text-lg font-semibold text-ink-900">{title}</h1>
      {subtitle && <p className="text-[13px] text-ink-400 mt-0.5">{subtitle}</p>}
    </div>
    {actions && <div className="flex items-center gap-2.5">{actions}</div>}
  </div>
);
