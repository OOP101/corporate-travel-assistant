import { ReactNode, useEffect } from 'react';
import { X } from 'lucide-react';

export interface DrawerProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}

/**
 * 右侧详情抽屉：管理台里查看详情用抽屉而非弹窗，
 * 好处是不打断列表上下文，也便于左右对照。
 */
export const Drawer = ({ open, title, subtitle, onClose, children, footer, width = 540 }: DrawerProps) => {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-ink-900/25" onClick={onClose} />
      <div
        className="drawer-panel relative h-full bg-white flex flex-col shadow-2xl"
        style={{ width }}
      >
        <div
          className="h-14 shrink-0 flex items-center justify-between px-5"
          style={{ borderBottom: '1px solid var(--line)' }}
        >
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink-900 truncate">{title}</div>
            {subtitle && <div className="text-[11px] text-ink-400 truncate">{subtitle}</div>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-ink-400 hover:bg-gray-100 hover:text-ink-600 transition-colors shrink-0"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
        {footer && (
          <div
            className="shrink-0 px-5 py-3 bg-gray-50/70 flex items-center justify-end gap-2"
            style={{ borderTop: '1px solid var(--line)' }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};
