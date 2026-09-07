import { lazy, Suspense, useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom';
import {
  MessageSquare, Map, Bell, Building2, FileText, CheckCircle,
  Plane, ShieldCheck, LogOut, Loader2, Settings, Wallet, BarChart3,
} from 'lucide-react';
import { getAuth, clearAuth, isAdmin } from './api/auth';

// 页面按需加载：首屏只拉取当前路由的页面 chunk
const ChatPage = lazy(() => import('./pages/ChatPage'));
const TripsPage = lazy(() => import('./pages/TripsPage'));
const TripDetailPage = lazy(() => import('./pages/TripDetailPage'));
const AlertsPage = lazy(() => import('./pages/AlertsPage'));
const OrgPage = lazy(() => import('./pages/OrgPage'));
const PolicyPage = lazy(() => import('./pages/PolicyPage'));
const ApprovalPage = lazy(() => import('./pages/ApprovalPage'));
const ReimbursementPage = lazy(() => import('./pages/ReimbursementPage'));
const ReportsPage = lazy(() => import('./pages/ReportsPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));

function PageFallback() {
  return (
    <div className="flex justify-center py-24">
      <Loader2 className="animate-spin text-ink-400" size={24} />
    </div>
  );
}

const navGroups = [
  {
    label: '工作台',
    items: [
      { to: '/', icon: MessageSquare, label: '智能助手' },
      { to: '/trips', icon: Map, label: '差旅行程' },
      { to: '/alerts', icon: Bell, label: '实时监控' },
    ],
  },
  {
    label: '企业管理',
    adminOnly: true,
    items: [
      { to: '/org', icon: Building2, label: '组织管理' },
      { to: '/policy', icon: FileText, label: '差旅政策' },
      { to: '/approval', icon: CheckCircle, label: '审批流转' },
      { to: '/reimbursement', icon: Wallet, label: '报销管理' },
      { to: '/reports', icon: BarChart3, label: '报表中心' },
    ],
  },
  {
    label: '系统',
    adminOnly: true,
    items: [
      { to: '/admin', icon: Settings, label: '系统管理' },
    ],
  },
];

const pageTitles = {
  '/': { title: '智能助手', sub: '行智 · Journey Hub' },
  '/trips': { title: '差旅行程', sub: '策程 · Planner Core' },
  '/alerts': { title: '实时监控', sub: '感知 · Sense Engine' },
  '/org': { title: '组织管理', sub: '企业组织与人员' },
  '/policy': { title: '差旅政策', sub: '政策标准与文档库' },
  '/approval': { title: '审批流转', sub: '行程审批与合规' },
  '/reimbursement': { title: '报销管理', sub: '差旅费用报销与打款' },
  '/reports': { title: '报表中心', sub: '差旅与报销汇总分析' },
  '/admin': { title: '系统管理', sub: '模型与 LLM 服务配置' },
};

function Topbar({ user }) {
  const location = useLocation();
  const meta = pageTitles[location.pathname] || pageTitles['/'];
  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-6 bg-white border-b border-gray-100">
      <div className="flex items-baseline gap-2">
        <h1 className="text-[15px] font-semibold text-ink-900">{meta.title}</h1>
        <span className="text-xs text-ink-400">{meta.sub}</span>
      </div>
      <div className="flex items-center gap-4">
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
            <span className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">管理员</span>
          )}
        </div>
      </div>
    </header>
  );
}

function Sidebar({ user, onLogout }) {
  const groups = navGroups.filter((g) => !g.adminOnly || isAdmin());
  return (
    <aside className="w-56 shrink-0 bg-white border-r border-gray-100 flex flex-col">
      {/* Brand */}
      <div className="h-14 flex items-center gap-2.5 px-5 border-b border-gray-100 shrink-0">
        <div className="w-8 h-8 rounded-xl brand-mark text-white flex items-center justify-center shadow-sm">
          <Plane size={16} />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-ink-900">企业智行</div>
          <div className="text-[10px] text-ink-400 tracking-wide">CORPORATE JOURNEY HUB</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-2 mb-1.5 text-[11px] font-medium text-ink-400 tracking-wider">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] transition-colors ${
                      isActive
                        ? 'bg-primary-50 text-primary-600 font-medium'
                        : 'text-ink-600 hover:bg-gray-50 hover:text-ink-900'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon size={17} className={isActive ? 'text-primary-500' : 'text-ink-400'} />
                      <span>{label}</span>
                      {isActive && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-primary-500" />}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-3 py-3 border-t border-gray-100 space-y-0.5">
        <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] text-ink-400">
          <ShieldCheck size={17} />
          <span>v2.0 · 企业版</span>
        </div>
        <div onClick={onLogout} className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] text-ink-400 cursor-pointer hover:bg-gray-50 hover:text-ink-600 transition-colors">
          <LogOut size={17} />
          <span>退出登录</span>
        </div>
      </div>
    </aside>
  );
}

export default function App() {
  const [auth, setAuth] = useState(getAuth());

  // 登录门卫：未登录只渲染登录页
  if (!auth?.token) {
    return (
      <Suspense fallback={<PageFallback />}>
        <LoginPage onLogin={setAuth} />
      </Suspense>
    );
  }

  const handleLogout = () => {
    clearAuth();
    setAuth(null);
  };

  return (
    <BrowserRouter>
      <div className="h-screen flex bg-surface">
        <Sidebar user={auth} onLogout={handleLogout} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Topbar user={auth} />
          <main className="flex-1 overflow-y-auto">
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/" element={<ChatPage />} />
                <Route path="/trips" element={<TripsPage />} />
                <Route path="/trips/:tripId" element={<TripDetailPage />} />
                <Route path="/alerts" element={<AlertsPage />} />
                <Route path="/org" element={<OrgPage />} />
                <Route path="/policy" element={<PolicyPage />} />
                <Route path="/approval" element={<ApprovalPage />} />
                <Route path="/reimbursement" element={<ReimbursementPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/admin" element={<AdminPage />} />
              </Routes>
            </Suspense>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
