import { useState } from 'react';
import { Plane, Loader2, User, Lock, Check, Sparkles, ShieldCheck, Radio } from 'lucide-react';
import { login, register } from '../api/auth';

const MIN_PASSWORD = 8;

const HIGHLIGHTS = [
  { icon: Sparkles, title: '一句话生成可执行行程', desc: '流式输出，边生成边可读；商务场景模板直出' },
  { icon: ShieldCheck, title: '差标先行，规则不让位', desc: '政策预检 → 超标标注 → 确认后才发起审批' },
  { icon: Radio, title: '实时感知，异常主动提醒', desc: '航班 · 铁路 · 天气 · 路况 · 景点状态持续监控' },
];

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

  const fieldCls = 'w-full pl-9 pr-3 py-2.5 text-sm bg-white border border-gray-200 rounded-lg focusable';

  return (
    <div className="h-screen flex">
      {/* 左侧品牌区 */}
      <div
        className="hidden lg:flex w-[44%] xl:w-[40%] flex-col justify-between p-10 xl:p-12"
        style={{ background: 'var(--sidebar-bg)' }}
      >
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl brand-mark text-white flex items-center justify-center shadow-sm">
            <Plane size={17} />
          </div>
          <div className="leading-tight">
            <div className="text-[14px] font-semibold text-white">企业智行</div>
            <div className="text-[9px] tracking-[0.1em] sidebar-muted">CORPORATE JOURNEY HUB</div>
          </div>
        </div>

        <div>
          <h1 className="text-[26px] xl:text-[30px] leading-snug font-semibold text-white mb-3">
            差旅这件事，<br />从一句话到可执行的行程
          </h1>
          <p className="text-[13px] text-slate-400 leading-relaxed mb-8 max-w-md">
            行程生成、差标校验、审批流转、费用报销与实时感知，收敛在同一条链路上。
          </p>

          <div className="space-y-4">
            {HIGHLIGHTS.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="flex items-start gap-3">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                  style={{ background: 'rgba(99, 102, 241, 0.16)' }}
                >
                  <Icon size={15} className="text-indigo-300" />
                </div>
                <div className="min-w-0">
                  <div className="text-[13px] font-medium text-slate-200">{title}</div>
                  <div className="text-[12px] text-slate-500 leading-relaxed mt-0.5">{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="text-[11px] sidebar-muted">
          v2.0 · 企业版　·　组织 · 政策 · 审批 · 报销 全链路打通
        </div>
      </div>

      {/* 右侧表单 */}
      <div className="flex-1 flex items-center justify-center app-shell px-6">
        <div className="w-full max-w-sm">
          <div className="flex flex-col items-center mb-7 lg:hidden">
            <div className="w-12 h-12 rounded-2xl brand-mark text-white flex items-center justify-center shadow-md mb-3">
              <Plane size={22} />
            </div>
            <h1 className="text-xl font-semibold text-ink-900">企业智行</h1>
            <p className="text-xs text-ink-400 tracking-wide mt-1">CORPORATE JOURNEY HUB</p>
          </div>

          <div className="mb-5">
            <h2 className="text-base font-semibold text-ink-900">
              {isRegister ? '创建账号' : '登录工作台'}
            </h2>
            <p className="text-[12px] text-ink-400 mt-1">
              {isRegister ? '注册后自动登录，可立即开始规划行程' : '用企业账号进入差旅工作台'}
            </p>
          </div>

          <div className="flex gap-1 p-1 mb-4 bg-white border border-gray-200 rounded-lg">
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
                  className={fieldCls}
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
                  className={fieldCls}
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
                    className={fieldCls}
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
    </div>
  );
}
