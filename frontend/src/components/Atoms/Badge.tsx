import { ReactNode } from 'react';

export type BadgeTone = 'blue' | 'green' | 'amber' | 'red' | 'gray' | 'purple' | 'primary' | 'pink';

export interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  icon?: ReactNode;
  className?: string;
}

const TONES: Record<BadgeTone, string> = {
  blue: 'bg-blue-50 text-blue-700 border-blue-100',
  green: 'bg-emerald-50 text-emerald-700 border-emerald-100',
  amber: 'bg-amber-50 text-amber-700 border-amber-100',
  red: 'bg-red-50 text-red-700 border-red-100',
  gray: 'bg-gray-100 text-gray-600 border-gray-200',
  purple: 'bg-purple-50 text-purple-700 border-purple-100',
  primary: 'bg-primary-50 text-primary-700 border-primary-100',
  pink: 'bg-pink-50 text-pink-700 border-pink-100',
};

export const Badge = ({ children, tone = 'gray', icon, className }: BadgeProps) => (
  <span
    className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full border ${TONES[tone]} ${className || ''}`}
  >
    {icon}
    {children}
  </span>
);
