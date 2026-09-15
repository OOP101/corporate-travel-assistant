import { useState, useEffect } from 'react';
import { Bell, RefreshCw, Info, Loader2, Plane, Cloud, Car, MapPin, Radio, Activity, ShieldAlert, TrainFront, Plus } from 'lucide-react';
import { getMonitorStatus, manualCheck, subscribeMonitor } from '../api/sense';
import { listTrips } from '../api/planner';
import { currentUserId } from '../api/auth';
import { PageHeader, StatCard, Badge, Button, EmptyState } from '../components';

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

const inputCls = "px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-primary-400";

export default function AlertsPage() {
  const [status, setStatus] = useState(null);
  const [newAlerts, setNewAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);

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
    } catch (e) {
      console.error(e);
    }
    setChecking(false);
  };

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="实时监控"
        subtitle="航班 · 铁路 12306 · 天气 · 路况 · 景点状态，主动感知并推送提醒"
        actions={
          <div className="flex gap-2">
            <Button type="secondary" onClick={openForm}>
              <Plus size={14} /> 新建订阅
            </Button>
            <Button type="secondary" onClick={handleCheck} disabled={checking}>
              <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
              手动检查
            </Button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        {loading ? (
          <div className="flex justify-center py-24"><Loader2 className="animate-spin text-ink-400" size={26} /></div>
        ) : !status ? (
          <EmptyState icon={<Bell size={24} />} title="无法连接感知引擎" description="请确认 Sense Engine (:8003) 已启动" />
        ) : (
          <div className="max-w-4xl mx-auto space-y-5">
            {/* 订阅表单 */}
            {showForm && (
              <div className="card p-5">
                <h2 className="text-sm font-semibold text-ink-900 mb-4">新建监控订阅</h2>

                <label className="block text-[13px] font-medium text-ink-600 mb-1.5">监控的行程 *</label>
                <select value={form.trip_id} onChange={(e) => pickTrip(e.target.value)} className={`w-full mb-3 ${inputCls}`}>
                  <option value="">选择行程…</option>
                  {trips.map((t) => (
                    <option key={t.trip_id} value={t.trip_id}>{t.title || t.trip_id}</option>
                  ))}
                </select>

                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1.5">✈️ 航班号（可选）</label>
                    <input value={form.flight_number} onChange={(e) => setField('flight_number', e.target.value)}
                      className={`w-full ${inputCls}`} placeholder="如 CA1234" />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1.5">🚄 车次（可选）</label>
                    <input value={form.train_code} onChange={(e) => setField('train_code', e.target.value)}
                      className={`w-full ${inputCls}`} placeholder="如 G102" />
                  </div>
                </div>

                {form.train_code.trim() && (
                  <div className="grid grid-cols-3 gap-3 mb-3 bg-primary-50/60 border border-primary-100 rounded-xl p-3">
                    <div>
                      <label className="block text-[12px] font-medium text-ink-600 mb-1">出发车站</label>
                      <input value={form.train_from} onChange={(e) => setField('train_from', e.target.value)}
                        className={`w-full ${inputCls}`} placeholder="广州南" />
                    </div>
                    <div>
                      <label className="block text-[12px] font-medium text-ink-600 mb-1">到达车站</label>
                      <input value={form.train_to} onChange={(e) => setField('train_to', e.target.value)}
                        className={`w-full ${inputCls}`} placeholder="北京西" />
                    </div>
                    <div>
                      <label className="block text-[12px] font-medium text-ink-600 mb-1">乘车日期</label>
                      <input type="date" value={form.train_date} onChange={(e) => setField('train_date', e.target.value)}
                        className={`w-full ${inputCls}`} />
                    </div>
                    <p className="col-span-3 text-xs text-ink-400">监控该车次是否停运/取消、有无余票（12306 数据，异常时降级模拟）</p>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">目的地城市（天气监控）</label>
                    <input value={form.destination} onChange={(e) => setField('destination', e.target.value)}
                      className={`w-full ${inputCls}`} placeholder="如 北京" />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">出发城市（路况监控）</label>
                    <input value={form.origin} onChange={(e) => setField('origin', e.target.value)}
                      className={`w-full ${inputCls}`} placeholder="如 广州" />
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

            {/* Status */}
            <div className="grid grid-cols-3 gap-4">
              <StatCard
                icon={<Radio size={20} />}
                label="监控订阅"
                value={status.subscription_count || 0}
                tone="primary"
              />
              <StatCard
                icon={<Activity size={20} />}
                label="活跃数据源"
                value={status.active_sources?.length || 0}
                tone="blue"
              />
              <StatCard
                icon={<ShieldAlert size={20} />}
                label="累计提醒"
                value={status.total_alerts || 0}
                tone="amber"
              />
            </div>

            {/* Subscriptions */}
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
                      <div className="flex gap-1.5 shrink-0">
                        {sub.check_weather && <Badge tone="blue">天气</Badge>}
                        {sub.check_traffic && <Badge tone="amber">路况</Badge>}
                        {sub.check_attractions && <Badge tone="green">景点</Badge>}
                        {sub.flight_number && <Badge tone="purple">航班</Badge>}
                        {sub.train_code && <Badge tone="primary">铁路</Badge>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* New alerts */}
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
