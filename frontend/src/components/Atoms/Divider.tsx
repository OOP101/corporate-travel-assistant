export interface DividerProps {
  className?: string;
}

export const Divider = ({ className }: DividerProps) => (
  <hr className={`my-6 border-t border-gray-200 ${className || ''}`} />
);