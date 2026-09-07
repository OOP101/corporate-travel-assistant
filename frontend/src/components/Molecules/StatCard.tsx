import { ReactNode } from 'react';

export interface StatCardProps {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: 'primary' | 'green' | 'amber' | 'purple' | 'blue';
}

const TONES = {
  primary: 'bg-primary-50 text-primary-600',
  green: 'bg-emerald-50 text-emerald-600',
  amber: 'bg-amber-50 text-amber-600',
  purple: 'bg-purple-50 text-purple-600',
  blue: 'bg-blue-50 text-blue-600',
};

export const StatCard = ({ icon, label, value, hint, tone = 'primary' }: StatCardProps) => (
  <div className="card p-4 flex items-center gap-3.5">
    <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${TONES[tone]}`}>
      {icon}
    </div>
    <div className="min-w-0">
      <div className="text-[13px] text-ink-400">{label}</div>
      <div className="text-xl font-semibold text-ink-900 leading-tight">{value}</div>
      {hint && <div className="text-[11px] text-ink-400 mt-0.5">{hint}</div>}
    </div>
  </div>
);
