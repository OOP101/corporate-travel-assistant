import { ReactNode } from 'react';

export interface ButtonProps {
  children: ReactNode;
  type?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'lg' | 'md' | 'sm' | 'xs';
  disabled?: boolean;
  className?: string;
  onClick?: () => void;
  loading?: boolean;
  icon?: string;
  style?: React.CSSProperties;
  block?: boolean;
  fullWidth?: boolean;
}

export const Button = ({
  children,
  type = 'primary',
  size = 'md',
  disabled,
  className,
  onClick,
  loading,
  icon,
  style,
  block = false,
  fullWidth = false,
}: ButtonProps) => {
  const sizeClasses = {
    lg: 'px-5 py-2.5 text-sm',
    md: 'px-4 py-2 text-sm',
    sm: 'px-2.5 py-1.5 text-xs',
    xs: 'px-2 py-1 text-xs',
  };

  const typeStyles = {
    primary: 'bg-primary-600 text-white hover:bg-primary-700 shadow-sm shadow-primary-200',
    secondary: 'bg-white text-ink-600 border border-gray-200 hover:bg-gray-50 hover:border-gray-300',
    ghost: 'text-primary-600 hover:bg-primary-50',
    danger: 'bg-red-600 text-white hover:bg-red-700 shadow-sm shadow-red-200',
  };

  const sizeObj = sizeClasses[size];
  const typeObj = typeStyles[type];

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400 focus-visible:ring-offset-1 disabled:opacity-45 disabled:cursor-not-allowed ${sizeObj} ${typeObj} ${block || fullWidth ? 'w-full' : ''} ${className || ''}`}
      style={style}
    >
      {loading ? (
        <svg
          className="animate-spin w-4 h-4"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
          />
        </svg>
      ) : (
        icon && <span>{icon}</span>
      )}
      {children}
    </button>
  );
};
