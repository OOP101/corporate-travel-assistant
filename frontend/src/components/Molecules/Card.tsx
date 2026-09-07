import { ReactNode } from 'react';

export interface CardProps {
  header?: string;
  headerIcon?: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export const Card = ({
  header,
  headerIcon,
  children,
  footer,
  className,
  style,
}: CardProps) => {
  return (
    <div className={`card ${className || ''}`} style={style}>
      {header && (
        <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
          {headerIcon && <span className="text-primary-500">{headerIcon}</span>}
          <span className="text-sm font-semibold text-ink-900">{header}</span>
        </div>
      )}
      <div className="p-5">{children}</div>
      {footer && <div className="px-5 py-3 border-t border-gray-100">{footer}</div>}
    </div>
  );
};
