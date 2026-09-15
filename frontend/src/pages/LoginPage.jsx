import { useState } from 'react';
import { Plane, Loader2, User, Lock, Check } from 'lucide-react';
import { login, register } from '../api/auth';

const MIN_PASSWORD = 8;

export default function LoginPage({ onLogin }) {
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isRegister = mode === 'register';

  const switchMode = (next) => {
    setMode(next);
    setError('');
    setPassword('');
    setConfirm('');
  };

  // 注册端的即时校验：与后端规则保持一致，避免把必然失败的请求发出去
  const usernameOk = /^[A-Za-z0-9_.-]{3,32}$/.test(username.trim());
  const passwordOk = password.length >= MIN_PASSWORD;
  const confirmOk = confirm === password;
  const canSubmit = isRegister
    ? usernameOk && passwordOk && confirmOk
    : !!username.trim() && !!password;

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit || loading) return;
    setLoading(true);
    setError('');
    try {
      const res = isRegister
        ? await register(username.trim(), password)
        : await login(username.trim(), password);
      onLogin(res);
    } catch (err) {
      setError(err.message || (isRegister ? '注册失败' : '登录失败'));
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

        <div className="flex gap-1 p-1 mb-3 bg-white border border-gray-200 rounded-lg">
          {[
            { key: 'login', label: '登录' },
            { key: 'register', label: '注册' },
          ].map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => switchMode(t.key)}
              className={`flex-1 py-1.5 text-[13px] font-medium rounded-md transition-colors ${
                mode === t.key
                  ? 'bg-primary-600 text-white'
                  : 'text-ink-500 hover:text-ink-700'
              }`}
            >
              {t.label}
            </button>
          ))}
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
                placeholder={isRegister ? '3-32 位字母、数字或 . _ -' : '请输入用户名'}
                autoComplete="username"
                name="username"
                autoFocus
              />
            </div>
            {isRegister && username && !usernameOk && (
              <p className="mt-1 text-xs text-red-500">用户名需为 3-32 位，仅可含字母、数字、下划线、点或连字符</p>
            )}
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
                placeholder={isRegister ? `至少 ${MIN_PASSWORD} 位` : '请输入密码'}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                name="password"
              />
            </div>
            {isRegister && password && !passwordOk && (
              <p className="mt-1 text-xs text-red-500">密码至少 {MIN_PASSWORD} 位</p>
            )}
          </div>

          {isRegister && (
            <div>
              <label className="block text-[13px] font-medium text-ink-600 mb-1.5">确认密码</label>
              <div className="relative">
                <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="w-full pl-9 pr-3 py-2.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                  placeholder="请再次输入密码"
                  autoComplete="new-password"
                  name="confirm"
                />
              </div>
              {confirm && !confirmOk && (
                <p className="mt-1 text-xs text-red-500">两次输入的密码不一致</p>
              )}
            </div>
          )}

          {error && (
            <div className="text-[13px] text-red-500 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !canSubmit}
            className="w-full py-2.5 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {loading && <Loader2 size={15} className="animate-spin" />}
            {isRegister ? '注 册' : '登 录'}
          </button>

          {isRegister ? (
            <div className="text-xs text-ink-400 space-y-1.5">
              <p className="flex items-center gap-1.5">
                <Check size={13} className={usernameOk ? 'text-emerald-500' : 'text-gray-300'} />
                用户名 3-32 位，字母、数字或 . _ -
              </p>
              <p className="flex items-center gap-1.5">
                <Check size={13} className={passwordOk ? 'text-emerald-500' : 'text-gray-300'} />
                密码至少 {MIN_PASSWORD} 位
              </p>
              <p className="pt-0.5">注册后即自动登录，可随时开始规划行程。</p>
            </div>
          ) : (
            <p className="text-xs text-ink-400 text-center">
              管理员：admin / admin123　·　员工：web-user / 123456
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
