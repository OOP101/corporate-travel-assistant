import { useState, useEffect, useRef } from 'react';
import {
  Bell, RefreshCw, Info, Loader2, Plane, Cloud, Car, MapPin, Radio, Activity,
  ShieldAlert, TrainFront, Plus, Trash2, Zap, Search, X,
} from 'lucide-react';
import {
  getMonitorStatus, manualCheck, subscribeMonitor, unsubscribeMonitor, realtimeQuery,
} from '../api/sense';
import { listTrips } from '../api/planner';
import { currentUserId } from '../api/auth';
import {
  PageHeader, StatCard, Badge, Button, EmptyState, Tab, Card, TagInput,
  WeatherCard, FlightCard, TrainCard, ResultSummary, weatherSeverity,
} from '../components';

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

/* 常用城市 / 站点：一点即入列，省得手打。
   要增删城市，只改 COMMON_CITIES 这一行即可——顺序 = chips 展示顺序。 */
const COMMON_CITIES = [
  // 直辖市 / 一线
  '北京', '广州', '深圳', '天津', '重庆',
  // 省会 / 计划单列市 / 经济大市
  '西安', '成都', '杭州', '南京', '武汉', '长沙', '郑州', '青岛', '厦门', '苏州',
  '宁波', '济南', '合肥', '南昌', '昆明', '福州', '沈阳', '大连', '哈尔滨', '贵阳',
];
const COMMON_FLIGHTS = ['CA1234', 'MU5100', 'CZ3101', 'HU7801'];
const COMMON_TRAINS = ['G102', 'G7', 'D301', 'Z21'];
const DEFAULT_CITIES = ['西安', '北京', '广州', '深圳'];
const MAX_ITEMS = 8;
/** 西→东：先按输入顺序，异常项不挪位（避免卡片跳来跳去） */
const num = (v) => (typeof v === 'number' ? v : 0);

/**
 * 实时直查：问答路径同款接口，同步返回、不等监控订阅。
 * 后端是「单值查询」，多城市/多航班由前端并行拆请求，一值一卡。
 */
function QueryPanel() {
  const [type, setType] = useState('weather');
  const [cities, setCities] = useState(DEFAULT_CITIES);
  const [flights, setFlights] = useState([]);
  const [trains, setTrains] = useState([]);
  const [flightRoute, setFlightRoute] = useState({ origin: '', destination: '' });
  const [trainCtx, setTrainCtx] = useState({ train_from: '', train_to: '', train_date: '' });
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const runIdRef = useRef(0);   // 防竞态：重查后丢弃在途的旧响应
  const autoRef = useRef(false);

  const lists = { weather: cities, flight: flights, train: trains };
  const current = lists[type] || [];
  const canRun = current.length > 0;

  const setList = (v) => {
    if (type === 'weather') setCities(v);
    else if (type === 'flight') setFlights(v);
    else setTrains(v);
  };

  /** 打平成「一项 = 一张卡」的查询清单 */
  const buildItems = () => {
    if (type === 'weather') {
      return cities.map((c) => ({ key: `w:${c}`, label: c, payload: { type: 'weather', city: c } }));
    }
    if (type === 'flight') {
      return flights.map((f) => ({
        key: `f:${f}`,
        label: f,
        payload: {
          type: 'flight',
          flight_number: f,
          origin: flightRoute.origin.trim(),
          destination: flightRoute.destination.trim(),
        },
      }));
    }
    return trains.map((t) => ({
      key: `t:${t}`,
      label: t,
      payload: {
        type: 'train',
        train_code: t,
        train_from: trainCtx.train_from.trim(),
        train_to: trainCtx.train_to.trim(),
        train_date: trainCtx.train_date.trim(),
      },
    }));
  };

  const run = async () => {
    const items = buildItems();
    if (!items.length) return;
    const runId = ++runIdRef.current;
    setLoading(true);
    setRows(items.map((it) => ({ key: it.key, label: it.label, status: 'loading' })));

    // 并行发出、逐张落地：先回来的先渲染，不等最慢的那个
    await Promise.all(items.map(async (it, idx) => {
      try {
        const res = await realtimeQuery(it.payload);
        if (runId !== runIdRef.current) return;
        setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, status: 'ok', data: res.data } : r)));
      } catch (e) {
        if (runId !== runIdRef.current) return;
        setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, status: 'err', error: e.message || '查询失败' } : r)));
      }
    }));
    if (runId === runIdRef.current) setLoading(false);
  };

  // 进来就先把默认城市查出来，省掉「切过来还要再点一下」
  useEffect(() => {
    if (autoRef.current) return;
    autoRef.current = true;
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 切类型时清掉上一类的结果，避免张冠李戴
  const switchType = (v) => {
    runIdRef.current += 1;   // 丢弃在途响应
    setType(v);
    setRows([]);
    setLoading(false);
  };

  const toggleCommon = (v) => {
    const has = current.includes(v);
    if (has) setList(current.filter((x) => x !== v));
    else if (current.length < MAX_ITEMS) setList([...current, v]);
  };

  const doneCount = rows.filter((r) => r.status !== 'loading').length;
  const failedCount = rows.filter((r) => r.status === 'err').length;
  const alertCount = rows.filter((r) => {
    if (r.status !== 'ok' || !r.data) return false;
    if (type === 'weather') return !!weatherSeverity(r.data.condition, r.data.temp);
    if (type === 'flight') return r.data.status === 'delayed' || r.data.status === 'cancelled';
    return r.data.status === 'soldout' || r.data.status === 'cancelled';
  }).length;
  const mockAll = rows.length > 0 && rows.every((r) => r.status === 'ok' && r.data?.mock);

  const gridCls = type === 'weather'
    ? 'grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4'
    : 'grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3';

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <Card>
        <div className="flex items-start gap-2.5 text-[12px] text-ink-600 leading-relaxed">
          <Zap size={14} className="text-primary-500 mt-0.5 shrink-0" />
          <span>
            问答路径的同一个接口：同步直查、立即返回，不建立监控订阅。支持一次填多个值 —— 多城市天气 /
            多航班 / 多车次并行查询，一值一卡；需要持续盯变化时才走「监控订阅」。
          </span>
        </div>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center gap-1.5 mb-4">
          {QUERY_TYPES.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => switchType(value)}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] border transition-colors ${
                type === value
                  ? 'bg-primary-50 text-primary-700 border-primary-200 font-medium'
                  : 'bg-white text-ink-600 border-gray-200 hover:border-primary-300'
              }`}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
          <span className="ml-auto text-[11px] text-ink-400">单次最多 {MAX_ITEMS} 项</span>
        </div>

        {type === 'weather' && (
          <>
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">城市（可多个）</label>
            <TagInput value={cities} onChange={setCities} placeholder="输入城市名后回车，如 西安" />
            <CommonChips options={COMMON_CITIES} selected={cities} onToggle={toggleCommon} />
          </>
        )}

        {type === 'flight' && (
          <>
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">航班号（可多个）</label>
            <TagInput value={flights} onChange={setFlights} placeholder="输入航班号后回车，如 CA1234" />
            <CommonChips options={COMMON_FLIGHTS} selected={flights} onToggle={toggleCommon} />
            <div className="grid grid-cols-2 gap-3 mt-3">
              <div>
                <label className="block text-[12px] font-medium text-ink-600 mb-1.5">出发城市（可选）</label>
                <input value={flightRoute.origin} onChange={(e) => setFlightRoute((r) => ({ ...r, origin: e.target.value }))}
                  className={inputCls} placeholder="留空则由数据源补齐" />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink-600 mb-1.5">到达城市（可选）</label>
                <input value={flightRoute.destination} onChange={(e) => setFlightRoute((r) => ({ ...r, destination: e.target.value }))}
                  className={inputCls} placeholder="留空则由数据源补齐" />
              </div>
            </div>
          </>
        )}

        {type === 'train' && (
          <>
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">车次（可多个）</label>
            <TagInput value={trains} onChange={setTrains} placeholder="输入车次后回车，如 G102" />
            <CommonChips options={COMMON_TRAINS} selected={trains} onToggle={toggleCommon} />
            <div className="grid grid-cols-3 gap-3 mt-3">
              <div>
                <label className="block text-[12px] font-medium text-ink-600 mb-1.5">出发站</label>
                <input value={trainCtx.train_from} onChange={(e) => setTrainCtx((c) => ({ ...c, train_from: e.target.value }))}
                  className={inputCls} placeholder="广州南" />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink-600 mb-1.5">到达站</label>
                <input value={trainCtx.train_to} onChange={(e) => setTrainCtx((c) => ({ ...c, train_to: e.target.value }))}
                  className={inputCls} placeholder="北京西" />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink-600 mb-1.5">乘车日期</label>
                <input type="date" value={trainCtx.train_date} onChange={(e) => setTrainCtx((c) => ({ ...c, train_date: e.target.value }))}
                  className={inputCls} />
              </div>
            </div>
            <p className="text-[11px] text-ink-400 mt-2">
              出发点/到达站/日期三者填齐才走 12306 真实查询，否则降级为模拟数据。
            </p>
          </>
        )}

        <div className="flex items-center justify-between gap-3 mt-4 pt-4" style={{ borderTop: '1px solid var(--line)' }}>
          <span className="text-[12px] text-ink-400">
            {canRun ? `将并行查询 ${current.length} 项` : '请先添加至少一项'}
          </span>
          <div className="flex items-center gap-2">
            {rows.length > 0 && (
              <Button type="secondary" size="sm" onClick={() => { setRows([]); setList([]); }}>
                <X size={13} className="mr-1" /> 清空
              </Button>
            )}
            <Button type="primary" size="sm" loading={loading} disabled={!canRun} onClick={run}>
              <Search size={14} className="mr-1.5" /> 立即查询
            </Button>
          </div>
        </div>
      </Card>

      {rows.length > 0 && (
        <div>
          <ResultSummary
            icon={type === 'weather' ? <Cloud size={15} className="text-primary-500" /> : type === 'flight' ? <Plane size={15} className="text-primary-500" /> : <TrainFront size={15} className="text-primary-500" />}
            title={type === 'weather' ? '城市天气' : type === 'flight' ? '航班动态' : '车次状态'}
            loading={loading}
            total={rows.length}
            done={doneCount}
            failed={failedCount}
            alertCount={alertCount}
            mockAll={mockAll}
            onRefresh={canRun ? run : undefined}
          />

          <div className={gridCls}>
            {rows.map((r) => {
              const pending = r.status === 'loading';
              if (type === 'weather') {
                return <WeatherCard key={r.key} city={r.label} data={r.data} loading={pending} error={r.error} />;
              }
              if (type === 'flight') {
                return <FlightCard key={r.key} flightNumber={r.label} data={r.data} loading={pending} error={r.error} />;
              }
              return (
                <TrainCard
                  key={r.key}
                  query={{
                    train_code: r.label,
                    train_from: trainCtx.train_from,
                    train_to: trainCtx.train_to,
                    train_date: trainCtx.train_date,
                  }}
                  data={r.data}
                  loading={pending}
                  error={r.error}
                />
              );
            })}
          </div>

          <details className="card p-4 mt-3">
            <summary className="cursor-pointer text-[12px] text-ink-500 select-none">
              查看原始返回（JSON）
            </summary>
            <div className="mt-3 space-y-3">
              {rows.map((r) => (
                <div key={r.key}>
                  <div className="text-[11px] font-medium text-ink-500 mb-1">{r.label}</div>
                  <pre className="text-[11px] leading-relaxed bg-gray-50 border border-gray-100 rounded-lg p-3 overflow-auto max-h-60 text-ink-700">
                    {JSON.stringify(r.data ?? { error: r.error || '查询中' }, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

/** 常用值快捷 chips：一点加入，再点移除 */
function CommonChips({ options, selected, onToggle }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
      <span className="text-[11px] text-ink-400">常用：</span>
      {options.map((v) => {
        const on = selected.includes(v);
        return (
          <button
            key={v}
            type="button"
            onClick={() => onToggle(v)}
            className={`px-2 py-0.5 rounded-full text-[11px] border transition-colors ${
              on
                ? 'bg-primary-50 text-primary-700 border-primary-200 font-medium'
                : 'bg-white text-ink-500 border-gray-200 hover:border-primary-300'
            }`}
          >
            {v}
          </button>
        );
      })}
    </div>
  );
}
