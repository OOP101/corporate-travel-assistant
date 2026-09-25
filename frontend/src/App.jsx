import { lazy, Suspense, useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { getAuth, clearAuth, isAdmin } from './api/auth';
import { Sidebar, Topbar, CommandPalette } from './components';

// 页面按需加载：首屏只拉取当前路由的页面 chunk
const ConsolePage = lazy(() => import('./pages/ConsolePage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const TripsPage = lazy(() => import('./pages/TripsPage'));
const TripDetailPage = lazy(() => import('./pages/TripDetailPage'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const PolicyPage = lazy(() => import('./pages/PolicyPage'));
const CorpusPage = lazy(() => import('./pages/CorpusPage'));
const ApprovalPage = lazy(() => import('./pages/ApprovalPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));

function PageFallback() {
  return (
    <div className="flex justify-center py-24">
      <Loader2 className="animate-spin text-ink-400" size={24} />
    </div>
  );
}

export default function App() {
  const [auth, setAuth] = useState(getAuth());
  const [cmdOpen, setCmdOpen] = useState(false);

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
      <div className="h-screen flex app-shell">
        <Sidebar user={auth} isAdmin={isAdmin()} onLogout={handleLogout} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Topbar user={auth} onOpenCommand={() => setCmdOpen(true)} />
          <main className="flex-1 overflow-y-auto">
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/" element={<ConsolePage />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/trips" element={<TripsPage />} />
                <Route path="/trips/:tripId" element={<TripDetailPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="/policy" element={<PolicyPage />} />
                <Route path="/corpus" element={<CorpusPage />} />
                <Route path="/approval" element={<ApprovalPage />} />
                <Route path="/admin" element={<AdminPage />} />
              </Routes>
            </Suspense>
          </main>
        </div>
      </div>
      {/* 全局跳转：常挂在壳上，⌘K 可在任意页面唤起 */}
      <CommandPalette open={cmdOpen} onOpenChange={setCmdOpen} />
    </BrowserRouter>
  );
}
