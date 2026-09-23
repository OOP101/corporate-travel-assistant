import { useEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { Plane, LogOut, ChevronDown } from 'lucide-react';
import {
  HOME_ITEM,
  WORKSPACE_ITEMS,
  ENTERPRISE_GROUP,
  visibleAccountItems,
  groupOfPath,
} from '../../config/nav';

export interface SidebarProps {
  user?: { username?: string; role?: string } | null;
  isAdmin: boolean;
  onLogout: () => void;
}

const COLLAPSE_KEY = 'cjh_nav_collapsed';

/**
 * 记录「用户主动折叠过」的分组；没记录的默认展开。
 *
 * 语义是「记录 collapsed」而不是「记录 expanded」——缺省即展开，这样首次访问
 * 就能一眼看全管理入口，用户真要收起时才记住。反过来写会出现「明明想默认
 * 展开、结果靠 localStorage 缺省值兜成折叠」的别扭状态。
 */
function readCollapsed(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '{}') || {};
  } catch {
    return {};
  }
}

/** 统一样式的导航项（侧边栏与用户菜单共用） */
function Item({ to, icon: Icon, label, onNavigate }: any) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      onClick={onNavigate}
      className={({ isActive }: any) => `nav-item ${isActive ? 'is-active' : ''}`}
    >
      <Icon size={16} className="shrink-0" />
      <span className="truncate">{label}</span>
    </NavLink>
  );
}

/**
 * 深色侧边栏：数据台的骨架。
 *
 * 分层（参考 Linear / Vercel / Stripe Dashboard）：
 *   中控台置顶 → 主工作区 4 项常显（无分组标题）→ 企业管理可折叠（默认展开）
 *   → 账户项下沉到左下角用户菜单。命令面板与中控台共同承接低频入口。
 */
export const Sidebar = ({ user, isAdmin, onLogout }: SidebarProps) => {
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(readCollapsed);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const accountItems = visibleAccountItems(isAdmin);
  const enterpriseOpen = !collapsed[ENTERPRISE_GROUP.id];

  // 折叠状态持久化
  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify(collapsed));
  }, [collapsed]);

  // 进入某分组页面时自动展开该组，否则会出现「人在页面里、导航却是折叠的」
  useEffect(() => {
    const gid = groupOfPath(pathname);
    if (gid) setCollapsed((c) => (c[gid] ? { ...c, [gid]: false } : c));
  }, [pathname]);

  // 切换路由后自动收起用户菜单
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // 点击外部 / Esc 关闭用户菜单
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  return (
    <aside className="app-sidebar w-[228px] shrink-0 flex flex-col" style={{ background: 'var(--sidebar-bg)' }}>
      <div
        className="h-14 flex items-center gap-2.5 px-4 shrink-0"
        style={{ borderBottom: '1px solid var(--sidebar-line)' }}
      >
        <div className="w-8 h-8 rounded-xl brand-mark text-white flex items-center justify-center shadow-sm shrink-0">
          <Plane size={16} />
        </div>
        <div className="leading-tight min-w-0">
          <div className="text-[13px] font-semibold text-white truncate">企业智行</div>
          <div className="text-[9px] tracking-[0.08em] sidebar-muted truncate">CORPORATE JOURNEY HUB</div>
        </div>
      </div>

      <nav className="nav-scroll flex-1 overflow-y-auto sidebar-scroll px-3">
        {/* 中控台：落地页，单独置顶 */}
        <div className="nav-group">
          <div className="space-y-0.5">
            <Item {...HOME_ITEM} />
          </div>
        </div>

        {/* 主工作区：常显，不加分组标题 */}
        <div className="nav-group">
          <div className="space-y-0.5">
            {WORKSPACE_ITEMS.map((item) => (
              <Item key={item.to} {...item} />
            ))}
          </div>
        </div>

        {/* 企业管理：可折叠（默认展开；组内有当前页时自动展开） */}
        {isAdmin && (
          <div className="nav-group">
            <button
              type="button"
              onClick={() =>
                setCollapsed((c) => ({ ...c, [ENTERPRISE_GROUP.id]: !c[ENTERPRISE_GROUP.id] }))
              }
              aria-expanded={enterpriseOpen}
              className={`nav-group-toggle ${enterpriseOpen ? 'is-open' : ''}`}
            >
              <span>{ENTERPRISE_GROUP.label}</span>
              <ChevronDown size={13} />
            </button>
            {enterpriseOpen && (
              <div className="space-y-0.5">
                {ENTERPRISE_GROUP.items.map((item) => (
                  <Item key={item.to} {...item} />
                ))}
              </div>
            )}
          </div>
        )}
      </nav>

      {/* 账户区：全部收进左下角用户菜单 */}
      <div
        className="relative px-3 py-2.5 shrink-0"
        ref={menuRef}
        style={{ borderTop: '1px solid var(--sidebar-line)' }}
      >
        {menuOpen && (
          <div className="user-menu">
            <div className="user-menu-label">账户</div>
            <div className="space-y-0.5">
              {accountItems.map((item) => (
                <Item key={item.to} {...item} onNavigate={() => setMenuOpen(false)} />
              ))}
            </div>
            <hr />
            <button
              type="button"
              onClick={onLogout}
              className="nav-item danger w-full text-left cursor-pointer bg-transparent border-0"
            >
              <LogOut size={15} className="shrink-0" />
              <span>退出登录</span>
            </button>
          </div>
        )}

        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          aria-expanded={menuOpen}
          className="nav-item w-full text-left cursor-pointer bg-transparent border-0"
        >
          <span className="w-[22px] h-[22px] rounded-full brand-mark text-white text-[10px] font-semibold flex items-center justify-center shrink-0">
            {String(user?.username || '?').slice(0, 1).toUpperCase()}
          </span>
          <span className="truncate min-w-0 flex-1">{user?.username || '未登录'}</span>
          <span className="text-[10px] sidebar-muted shrink-0">
            {user?.role === 'admin' ? '管理员' : '成员'}
          </span>
          <ChevronDown size={13} className={`shrink-0 transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
        </button>
      </div>
    </aside>
  );
};
