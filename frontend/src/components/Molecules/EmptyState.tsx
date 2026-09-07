import { ReactNode } from 'react';

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

export const EmptyState = ({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) => {
  return (
    <div className={`text-center py-14 ${className || ''}`}>
      {icon && (
        <div className="w-14 h-14 mx-auto mb-3.5 rounded-2xl bg-gray-50 border border-gray-100 flex items-center justify-center text-gray-300">
          {icon}
        </div>
      )}
      <h3 className="text-[15px] font-semibold text-ink-900">{title}</h3>
      {description && (
        <p className="mt-1.5 text-sm text-ink-400">{description}</p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-primary-600 bg-primary-50 rounded-lg hover:bg-primary-100 transition-colors"
        >
          {action.label}
        </button>
      )}
    </div>
  );
};
