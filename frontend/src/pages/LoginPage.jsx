import { useState } from 'react';
import { Plane, Loader2, User, Lock } from 'lucide-react';
import { login } from '../api/auth';

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password || loading) return;
    setLoading(true);
    setError('');
    try {
      const res = await login(username.trim(), password);
      onLogin(res);
    } catch (err) {
      setError(err.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-surface">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-2xl brand-mark text-white flex items-center justify-center shadow-md mb-3">
            <Plane size={22} />
          </div>
          <h1 className="text-xl font-semibold text-ink-900">企业智行</h1>
          <p className="text-xs text-ink-400 tracking-wide mt-1">CORPORATE JOURNEY HUB</p>
        </div>

        <form onSubmit={submit} className="card p-6 space-y-4">
          <div>
            <label className="block text-[13px] font-medium text-ink-600 mb-1.5">用户名</label>
            <div className="relative">
              <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full pl-9 pr-3 py-2.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                placeholder="请输入用户名"
                autoComplete="username"
                name="username"
                autoFocus
              />
            </div>
          </div>

          <div>
            <label className="block text-[13px] font-medium text-ink-600 mb-1.5">密码</label>
            <div className="relative">
              <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-9 pr-3 py-2.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                placeholder="请输入密码"
                autoComplete="current-password"
                name="password"
              />
            </div>
          </div>

          {error && (
            <div className="text-[13px] text-red-500 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="w-full py-2.5 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {loading && <Loader2 size={15} className="animate-spin" />}
            登 录
          </button>

          <p className="text-xs text-ink-400 text-center">
            管理员：admin / admin123　·　员工：web-user / 123456
          </p>
        </form>
      </div>
    </div>
  );
}
