import { useState, useEffect } from 'react';
import {
  Bell, RefreshCw, Info, Loader2, Plane, Cloud, Car, MapPin, Radio, Activity,
  ShieldAlert, TrainFront, Plus, Trash2, Zap, Search,
} from 'lucide-react';
import {
  getMonitorStatus, manualCheck, subscribeMonitor, unsubscribeMonitor, realtimeQuery,
} from '../api/sense';
import { listTrips } from '../api/planner';
import { currentUserId } from '../api/auth';
import { PageHeader, StatCard, Badge, Button, EmptyState, Tab, Card } from '../components';

const SEVERITY_META = {
  info: { tone: 'blue', border: 'border-blue-200', label: '提示' },
  warning: { tone: 'amber', border: 'border-amber-200', label: '预警' },
  critical: { tone: 'red', border: 'border-red-200', label: '严重' },
};

const SOURCE_ICONS = {
  flight: Plane,
  train: TrainFront,
  weather: Cloud,
  traffic: Car,
  attraction: MapPin,
};

const QUERY_TYPES = [
  { value: 'weather', label: '天气', icon: Cloud },
  { value: 'flight', label: '航班', icon: Plane },
  { value: 'train', label: '车次', icon: TrainFront },
];

const inputCls = 'px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-primary-400 w-full';

export default function AlertsPage() {
  const [tab, setTab] = useState('monitor');
  const [status, setStatus] = useState(null);
  const [newAlerts, setNewAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [removingId, setRemovingId] = useState('');

  // 订阅表单
  const [showForm, setShowForm] = useState(false);
  const [trips, setTrips] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [formMsg, setFormMsg] = useState('');
  const [form, setForm] = useState({
    trip_id: '', flight_number: '', train_code: '', train_from: '', train_to: '',
    train_date: '', destination: '', origin: '',
    check_weather: true, check_traffic: false, check_attractions: false, attractions: '',
  });

  const loadStatus = async () => {
    setLoading(true);
    try {
      const data = await getMonitorStatus();
      setStatus(data);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { loadStatus(); }, []);

  const openForm = async () => {
    setShowForm((v) => !v);
    if (!trips.length) {
      try {
        const res = await listTrips();
        setTrips(res.trips || []);
      } catch { /* 列表加载失败不阻塞表单 */ }
    }
  };

  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const pickTrip = (tripId) => {
    const trip = trips.find((t) => t.trip_id === tripId);
    setForm((f) => ({ ...f, trip_id, destination: trip?.destination || f.destination, origin: trip?.origin || f.origin }));
  };

  const submitForm = async () => {
    if (!form.trip_id) { setFormMsg('请先选择要监控的行程'); return; }
    setSubmitting(true);
    setFormMsg('');
    try {
      await subscribeMonitor({
        trip_id: form.trip_id,
        user_id: currentUserId(),
        flight_number: form.flight_number.trim(),
        train_code: form.train_code.trim(),
        train_from: form.train_from.trim(),
        train_to: form.train_to.trim(),
        train_date: form.train_date.trim(),
        destination: form.destination.trim(),
        origin: form.origin.trim(),
        check_weather: form.check_weather,
        check_traffic: form.check_traffic,
        check_attractions: form.check_attractions,
        attractions: form.attractions.trim() ? form.attractions.split(/[,，、]/).map((s) => s.trim()).filter(Boolean) : [],
      });
      setFormMsg('订阅成功');
      setShowForm(false);
      setForm((f) => ({ ...f, flight_number: '', train_code: '', train_from: '', train_to: '', train_date: '', attractions: '' }));
      await loadStatus();
    } catch (e) {
      setFormMsg('订阅失败: ' + e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCheck = async () => {
    setChecking(true);
    try {
      const data = await manualCheck();
      setNewAlerts(data.alerts || []);
      await loadStatus();
    } catch (e) {
      console.error(e);
    }
    setChecking(false);
  };

  const removeSubscription = async (tripId) => {
    if (!window.confirm(`取消行程 ${tripId} 的监控订阅？该行程将不再接收新的提醒。`)) return;
    setRemovingId(tripId);
    try {
      await unsubscribeMonitor(tripId);
      await loadStatus();
    } catch (e) {
      window.alert('取消失败：' + e.message);
    }
    setRemovingId('');
  };

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="实时监控"
        subtitle="航班 · 铁路 12306 · 天气 · 路况 · 景点状态，主动感知并推送提醒"
        actions={
          tab === 'monitor' ? (
            <div className="flex gap-2">
              <Button type="secondary" size="sm" onClick={openForm}>
                <Plus size={14} /> 新建订阅
              </Button>
              <Button type="secondary" size="sm" onClick={handleCheck} disabled={checking}>
                <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
                手动检查
              </Button>
            </div>
          ) : null
        }
      />

      <div className="mb-4">
        <Tab
          tabs={[
            { label: '监控订阅', value: 'monitor' },
            { label: '实时直查', value: 'query' },
          ]}
          defaultActive="monitor"
          onChange={setTab}
        />
      </div>

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        {tab === 'query' ? (
          <QueryPanel />
        ) : loading ? (
          <div className="flex justify-center py-24"><Loader2 className="animate-spin text-ink-400" size={26} /></div>
        ) : !status ? (
          <EmptyState icon={<Bell size={24} />} title="无法连接感知引擎" description="请确认 Sense Engine (:8003) 已启动" />
        ) : (
          <div className="max-w-4xl mx-auto space-y-5">
            {showForm && (
              <div className="card p-5">
                <h2 className="text-sm font-semibold text-ink-900 mb-4">新建监控订阅</h2>

                <label className="block text-[13px] font-medium text-ink-600 mb-1.5">监控的行程 *</label>
                <select value={form.trip_id} onChange={(e) => pickTrip(e.target.value)} className={`mb-3 ${inputCls}`}>
                  <option value="">选择行程…</option>
                  {trips.map((t) => (
                    <option key={t.trip_id} value={t.trip_id}>{t.title || t.trip_id}</option>
                  ))}
                </select>

                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1.5">航班号（可选）</label>
                    <input value={form.flight_number} onChange={(e) => setField('flight_number', e.target.value)}
                      className={inputCls} placeholder="如 CA1234" />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1.5">车次（可选）</label>
                    <input value={form.train_code} onChange={(e) => setField('train_code', e.target.value)}
                      className={inputCls} placeholder="如 G102" />
                  </div>
                </div>

                {form.train_code.trim() && (
                  <div className="grid grid-cols-3 gap-3 mb-3 bg-primary-50/60 border border-primary-100 rounded-xl p-3">
                    <div>
                      <label className="block text-[12px] font-medium text-ink-600 mb-1">出发车站</label>
                      <input value={form.train_from} onChange={(e) => setField('train_from', e.target.value)}
                        className={inputCls} placeholder="广州南" />
                    </div>
                    <div>
                      <label className="block text-[12px] font-medium text-ink-600 mb-1">到达车站</label>
                      <input value={form.train_to} onChange={(e) => setField('train_to', e.target.value)}
                        className={inputCls} placeholder="北京西" />
                    </div>
                    <div>
                      <label className="block text-[12px] font-medium text-ink-600 mb-1">乘车日期</label>
                      <input type="date" value={form.train_date} onChange={(e) => setField('train_date', e.target.value)}
                        className={inputCls} />
                    </div>
                    <p className="col-span-3 text-xs text-ink-400">监控该车次是否停运/取消、有无余票（12306 数据，异常时降级模拟）</p>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">目的地城市（天气监控）</label>
                    <input value={form.destination} onChange={(e) => setField('destination', e.target.value)}
                      className={inputCls} placeholder="如 北京" />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">出发城市（路况监控）</label>
                    <input value={form.origin} onChange={(e) => setField('origin', e.target.value)}
                      className={inputCls} placeholder="如 广州" />
                  </div>
                </div>

                <div className="flex items-center gap-5 mb-4 text-sm text-ink-600">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={form.check_weather} onChange={(e) => setField('check_weather', e.target.checked)} /> 天气
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={form.check_traffic} onChange={(e) => setField('check_traffic', e.target.checked)} /> 路况
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={form.check_attractions} onChange={(e) => setField('check_attractions', e.target.checked)} /> 景点
                  </label>
                  {form.check_attractions && (
                    <input value={form.attractions} onChange={(e) => setField('attractions', e.target.value)}
                      className={`flex-1 ${inputCls}`} placeholder="景点名，逗号分隔（可空=全默认）" />
                  )}
                </div>

                {formMsg && (
                  <div className={`text-[13px] rounded-lg px-3 py-2 mb-3 ${formMsg.includes('成功') ? 'text-emerald-600 bg-emerald-50 border border-emerald-100' : 'text-red-500 bg-red-50 border border-red-100'}`}>
                    {formMsg}
                  </div>
                )}
                <div className="flex justify-end">
                  <Button type="primary" onClick={submitForm} disabled={submitting || !form.trip_id}>
                    {submitting && <Loader2 size={14} className="animate-spin" />} 提交订阅
                  </Button>
                </div>
              </div>
            )}

            <div className="grid grid-cols-3 gap-4">
              <StatCard icon={<Radio size={20} />} label="监控订阅" value={status.subscription_count || 0} tone="primary" />
              <StatCard icon={<Activity size={20} />} label="活跃数据源" value={status.active_sources?.length || 0} tone="blue" />
              <StatCard icon={<ShieldAlert size={20} />} label="累计提醒" value={status.total_alerts || 0} tone="amber" />
            </div>

            {status.subscriptions?.length > 0 && (
              <div className="card p-5">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-sm font-semibold text-ink-900">订阅列表</h2>
                  <span className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-full px-2.5 py-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    监控运行中
                  </span>
                </div>
                <div className="space-y-2">
                  {status.subscriptions.map((sub) => (
                    <div key={sub.trip_id} className="flex items-center justify-between bg-gray-50/70 rounded-xl px-4 py-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-ink-900 font-mono">{sub.trip_id}</div>
                        <div className="text-xs text-ink-400 mt-0.5">
                          {sub.destination && `目的地: ${sub.destination}`}
                          {sub.flight_number && ` · 航班: ${sub.flight_number}`}
                          {sub.train_code && ` · 车次: ${sub.train_code}（${sub.train_from || '?'}→${sub.train_to || '?'}${sub.train_date ? ' ' + sub.train_date : ''}）`}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {sub.check_weather && <Badge tone="blue">天气</Badge>}
                        {sub.check_traffic && <Badge tone="amber">路况</Badge>}
                        {sub.check_attractions && <Badge tone="green">景点</Badge>}
                        {sub.flight_number && <Badge tone="purple">航班</Badge>}
                        {sub.train_code && <Badge tone="primary">铁路</Badge>}
                        <button
                          type="button"
                          onClick={() => removeSubscription(sub.trip_id)}
                          disabled={removingId === sub.trip_id}
                          className="ml-1.5 w-7 h-7 rounded-lg flex items-center justify-center text-ink-400 hover:bg-red-50 hover:text-red-600 transition-colors disabled:opacity-40"
                          title="取消监控"
                        >
                          {removingId === sub.trip_id
                            ? <Loader2 size={13} className="animate-spin" />
                            : <Trash2 size={14} />}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {newAlerts.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-ink-900 mb-3">本次检查 · 新提醒</h2>
                <div className="space-y-2.5">
                  {newAlerts.map((alert) => {
                    const Icon = SOURCE_ICONS[alert.source] || Info;
                    const meta = SEVERITY_META[alert.severity] || SEVERITY_META.info;
                    return (
                      <div key={alert.alert_id} className={`card p-4 border-l-4 ${meta.border} hover:shadow-md transition-shadow`}>
                        <div className="flex items-start gap-3">
                          <div className="w-9 h-9 rounded-xl bg-gray-50 border border-gray-100 flex items-center justify-center shrink-0">
                            <Icon size={17} className="text-ink-600" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="font-medium text-sm text-ink-900">{alert.title}</span>
                              <Badge tone={meta.tone}>{meta.label}</Badge>
                            </div>
                            <p className="text-sm text-ink-600 leading-relaxed">{alert.message}</p>
                            {alert.suggested_action && (
                              <p className="text-sm mt-1.5 text-primary-600 bg-primary-50 border border-primary-100 rounded-lg px-3 py-1.5 inline-block">
                                建议：{alert.suggested_action}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {status.subscriptions?.length === 0 && (
              <EmptyState
                icon={<Bell size={24} />}
                title="暂无监控订阅"
                description="点击右上角「新建订阅」，为行程订阅航班、铁路、天气、路况监控"
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** 实时直查：问答路径同款接口，同步返回、不等监控订阅 */
function QueryPanel() {
  const [type, setType] = useState('weather');
  const [form, setForm] = useState({
    city: '', flight_number: '', origin: '', destination: '',
    train_code: '', train_from: '', train_to: '', train_date: '',
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const run = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const payload = { type };
      if (type === 'weather') {
        payload.city = form.city.trim();
      } else if (type === 'flight') {
        Object.assign(payload, {
          flight_number: form.flight_number.trim(),
          origin: form.origin.trim(),
          destination: form.destination.trim(),
        });
      } else {
        Object.assign(payload, {
          train_code: form.train_code.trim(),
          train_from: form.train_from.trim(),
          train_to: form.train_to.trim(),
          train_date: form.train_date.trim(),
        });
      }
      const res = await realtimeQuery(payload);
      setResult(res);
    } catch (e) {
      setError(e.message || '查询失败');
    }
    setLoading(false);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <Card>
        <div className="flex items-start gap-2.5 text-[12px] text-ink-600 leading-relaxed">
          <Zap size={14} className="text-primary-500 mt-0.5 shrink-0" />
          <span>
            问答路径的同一个接口：同步直查、立即返回，不建立监控订阅。适合「现在天气怎么样」这类即时问题；
            需要持续盯变化时才走「监控订阅」。
          </span>
        </div>
      </Card>

      <Card>
        <div className="flex flex-wrap gap-1.5 mb-4">
          {QUERY_TYPES.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => { setType(value); setResult(null); setError(''); }}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] border transition-colors ${
                type === value
                  ? 'bg-primary-50 text-primary-700 border-primary-200 font-medium'
                  : 'bg-white text-ink-600 border-gray-200 hover:border-primary-300'
              }`}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {type === 'weather' && (
          <div className="mb-4">
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">城市</label>
            <input value={form.city} onChange={(e) => set('city', e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && run()}
              className={inputCls} placeholder="如 西安" />
          </div>
        )}

        {type === 'flight' && (
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div>
              <label className="block text-[12px] font-medium text-ink-600 mb-1.5">航班号</label>
              <input value={form.flight_number} onChange={(e) => set('flight_number', e.target.value)}
                className={inputCls} placeholder="CA1234" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink-600 mb-1.5">出发城市</label>
              <input value={form.origin} onChange={(e) => set('origin', e.target.value)}
                className={inputCls} placeholder="西安" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink-600 mb-1.5">到达城市</label>
              <input value={form.destination} onChange={(e) => set('destination', e.target.value)}
                className={inputCls} placeholder="北京" />
            </div>
          </div>
        )}

        {type === 'train' && (
          <div className="grid grid-cols-4 gap-3 mb-4">
            <div>
              <label className="block text-[12px] font-medium text-ink-600 mb-1.5">车次</label>
              <input value={form.train_code} onChange={(e) => set('train_code', e.target.value)}
                className={inputCls} placeholder="G102" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink-600 mb-1.5">出发站</label>
              <input value={form.train_from} onChange={(e) => set('train_from', e.target.value)}
                className={inputCls} placeholder="广州南" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink-600 mb-1.5">到达站</label>
              <input value={form.train_to} onChange={(e) => set('train_to', e.target.value)}
                className={inputCls} placeholder="北京西" />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-ink-600 mb-1.5">乘车日期</label>
              <input type="date" value={form.train_date} onChange={(e) => set('train_date', e.target.value)}
                className={inputCls} />
            </div>
          </div>
        )}

        <div className="flex justify-end">
          <Button type="primary" size="sm" loading={loading} onClick={run}>
            <Search size={14} className="mr-1.5" /> 立即查询
          </Button>
        </div>
      </Card>

      {error && (
        <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-[13px] text-red-700 leading-relaxed">
          {error}
        </div>
      )}

      {result && (
        <Card header="查询结果" headerIcon={<Zap size={15} />}>
          <div className="flex items-center gap-2 mb-3">
            <Badge tone="primary">{result.type}</Badge>
            <span className="text-[11px] text-ink-400">实时直查 · 同步返回</span>
          </div>
          <ValueView value={result.data} />
        </Card>
      )}
    </div>
  );
}

function ValueView({ value, depth = 0 }) {
  if (value === null || value === undefined) return <span className="text-ink-400">—</span>;

  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-ink-400">空</span>;
    return (
      <div className="space-y-1.5">
        {value.slice(0, 12).map((it, i) => (
          <div key={i} className="rounded-lg border border-gray-100 bg-gray-50/60 px-3 py-2">
            <ValueView value={it} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === 'object') {
    return (
      <div className="space-y-1.5">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="flex gap-3 text-[12px] items-start">
            <span className="text-ink-400 w-[110px] shrink-0 pt-0.5">{k}</span>
            <span className="text-ink-900 flex-1 min-w-0 break-words">
              <ValueView value={v} depth={depth + 1} />
            </span>
          </div>
        ))}
      </div>
    );
  }

  return <span>{String(value)}</span>;
}
