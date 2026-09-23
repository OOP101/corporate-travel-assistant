import { useLocation } from 'react-router-dom';
import { Search } from 'lucide-react';
import { resolvePageMeta } from '../../config/nav';
import { COMMAND_HINT } from '../Molecules/CommandPalette';

export interface TopbarProps {
  user?: { username?: string; role?: string } | null;
  onOpenCommand?: () => void;
}

export const Topbar = ({ user, onOpenCommand }: TopbarProps) => {
  const { pathname } = useLocation();
  const meta = resolvePageMeta(pathname);

  return (
    <header
      className="h-14 shrink-0 flex items-center justify-between px-6 bg-white gap-4"
      style={{ borderBottom: '1px solid var(--line)' }}
    >
      <div className="flex items-baseline gap-2 min-w-0">
        <h1 className="text-[15px] font-semibold text-ink-900 truncate">{meta.title}</h1>
        <span className="text-xs text-ink-400 truncate">{meta.sub}</span>
      </div>
      <div className="flex items-center gap-4 shrink-0">
        <button
          type="button"
          onClick={onOpenCommand}
          title={`全局跳转（${COMMAND_HINT}）`}
          className="hidden md:flex items-center gap-2 h-8 pl-2.5 pr-2 rounded-lg text-xs text-ink-400 cursor-pointer bg-transparent transition-colors hover:text-ink-600"
          style={{ border: '1px solid var(--line)' }}
        >
          <Search size={14} className="shrink-0" />
          <span>搜索页面与行程</span>
          <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-gray-50 border border-gray-200 text-ink-400">
            {COMMAND_HINT}
          </kbd>
        </button>
        <span className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-full px-2.5 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          服务运行中
        </span>
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full brand-mark text-white flex items-center justify-center text-xs font-semibold">
            智
          </div>
          <span className="text-sm text-ink-600 font-medium">{user?.username || '未登录'}</span>
          {user?.role === 'admin' && (
            <span className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">
              管理员
            </span>
          )}
        </div>
      </div>
    </header>
  );
};
