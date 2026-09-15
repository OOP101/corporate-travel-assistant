import { useState } from 'react';
import { Plane, TrainFront, Car, Calendar, MapPin, Users, Wallet, BedDouble, AlertTriangle, Loader2, Check, RotateCcw, X } from 'lucide-react';

const SCENE_LABELS = {
  business: '商务出差',
  meeting: '会议参展',
  visit: '客户拜访',
  team: '团队出行',
  personal: '个人出游',
};

const TRANSPORT_OPTIONS = [
  { value: 'airplane', label: '飞机', icon: Plane },
  { value: 'train', label: '高铁/火车', icon: TrainFront },
  { value: 'drive', label: '自驾', icon: Car },
];

const DEFAULTED_LABELS = {
  num_adults: '人数',
  num_children: '儿童数',
  num_elders: '老人数',
  budget_total: '预算',
  origin: '出发地',
  transport: '交通方式',
};

/** 把当日活动按上午/下午/晚间归并成一行摘要（PRD v2 §8 每日骨架） */
function dayBuckets(activities = []) {
  const buckets = { am: [], pm: [], eve: [] };
  for (const act of activities) {
    const h = parseInt((act.time_start || '').split(':')[0] || '0', 10);
    const title = act.title || act.location?.name || '';
    if (!title) continue;
    if (h < 12) buckets.am.push(title);
    else if (h < 18) buckets.pm.push(title);
    else buckets.eve.push(title);
  }
  return buckets;
}

/**
 * 方案确认卡（S4）—— ChatPage 与 TripsPage 共用。
 *
 * 展示：场景徽标 / 日期天数 / 目的地 / 人数 / 预算（含 [代填] 标注）/
 * 酒店建议（主选 + 备选可换，腾讯地图真实 POI）/ 每日骨架 / 政策预警条。
 * 操作：确认并提交审批 | 改参数重新生成 | 取消。
 */
export function TripConfirmCard({
  trip,
  defaulted = [],
  policy = null,
  busy = false,
  onConfirm,
  onEdit,
  onCancel,
}) {
  const [hotelIdx, setHotelIdx] = useState(0);
  const [transport, setTransport] = useState(
    TRANSPORT_OPTIONS.some((t) => t.value === trip?.transport) ? trip.transport : 'airplane'
  );
  if (!trip) return null;

  const hotels = trip.hotel_options || [];
  const days = trip.days || [];
  const party = (trip.travel_party || [])
    .map((p) => (typeof p === 'string' ? p : p?.name || p?.role || ''))
    .filter(Boolean)
    .join('、');

  const showPolicyWarn = policy?.has_violations;

  return (
    <div className="mt-2 rounded-2xl border border-primary-100 bg-white shadow-sm overflow-hidden">
      {/* 头部：场景徽标 + 标题 + 日期 */}
      <div className="bg-gradient-to-br from-primary-600 to-primary-500 text-white px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-white/20 border border-white/25">
            {SCENE_LABELS[trip.scene] || '出行方案'} · 草案待确认
          </span>
        </div>
        <h4 className="mt-1.5 text-sm font-semibold truncate">{trip.title || '未命名行程'}</h4>
        <div className="mt-0.5 text-[12px] text-white/85 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <span className="flex items-center gap-1"><Calendar size={12} />{trip.start_date} ~ {trip.end_date}（{days.length} 天）</span>
          {trip.destination && <span className="flex items-center gap-1"><MapPin size={12} />{trip.destination}</span>}
          {party && <span className="flex items-center gap-1"><Users size={12} />{party}</span>}
          {!!trip.budget_total && <span className="flex items-center gap-1"><Wallet size={12} />¥{Number(trip.budget_total).toLocaleString()}</span>}
        </div>
      </div>

      <div className="px-4 py-3 space-y-3">
        {/* 代填项标注（PRD v2 §4.1：代填值必须显式展示） */}
        {defaulted.length > 0 && (
          <div className="space-y-1">
            {defaulted.map((d, i) => (
              <div key={i} className="text-[12px] text-ink-600 flex items-start gap-1.5">
                <span className="shrink-0 mt-px text-[10px] font-semibold text-amber-600 bg-amber-50 border border-amber-200 rounded px-1.5 py-px">代填</span>
                <span>{DEFAULTED_LABELS[d.field] || d.field}：{d.note || d.value}</span>
              </div>
            ))}
          </div>
        )}

        {/* 交通方式选择（v2.1）：卡片式点选，默认飞机，随确认提交 */}
        <div className="rounded-xl bg-gray-50 border border-gray-100 px-3 py-2.5">
          <span className="flex items-center gap-1.5 text-[12px] font-medium text-ink-700">
            <Plane size={13} className="text-primary-500" /> 交通方式
            <span className="text-[11px] font-normal text-ink-400">往返大交通按此规划</span>
          </span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {TRANSPORT_OPTIONS.map((t) => {
              const Icon = t.icon;
              const active = transport === t.value;
              return (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setTransport(t.value)}
                  disabled={busy}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-[12px] rounded-xl border transition-colors ${
                    active
                      ? 'bg-primary-600 border-primary-600 text-white font-medium'
                      : 'bg-white border-gray-200 text-ink-600 hover:border-primary-300 hover:text-primary-600'
                  } disabled:opacity-50`}
                >
                  <Icon size={13} /> {t.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* 酒店建议：主选 + 「换一家」备选（真实 POI，价格以预订平台为准） */}
        {hotels.length > 0 && (
          <div className="rounded-xl bg-gray-50 border border-gray-100 px-3 py-2.5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-[12px] font-medium text-ink-700">
                <BedDouble size={13} className="text-primary-500" /> 酒店建议
              </span>
              {hotels.length > 1 && (
                <select
                  value={hotelIdx}
                  onChange={(e) => setHotelIdx(Number(e.target.value))}
                  className="text-[12px] bg-white border border-gray-200 rounded-lg px-2 py-1 text-ink-600 focus:outline-none focus:border-primary-300"
                >
                  {hotels.map((h, i) => (
                    <option key={i} value={i}>换一家：{h.name}</option>
                  ))}
                </select>
              )}
            </div>
            <div className="mt-1 text-[12px] text-ink-600">
              {hotels[hotelIdx]?.name}
              {hotels[hotelIdx]?.address && <span className="text-ink-400"> · {hotels[hotelIdx].address}</span>}
              <span className="text-ink-400"> · 价格以预订平台为准</span>
            </div>
          </div>
        )}

        {/* 每日骨架（只读预览） */}
        <div className="space-y-1.5">
          {days.map((d, i) => {
            const b = dayBuckets(d.activities);
            const fmt = (list) => list.slice(0, 2).join('、') + (list.length > 2 ? ` 等` : '');
            return (
              <div key={i} className="text-[12px] text-ink-600 flex gap-2">
                <span className="shrink-0 font-medium text-ink-700 w-14">Day {i + 1}</span>
                <span className="flex-1 truncate">
                  {[b.am.length && `上午 ${fmt(b.am)}`, b.pm.length && `下午 ${fmt(b.pm)}`, b.eve.length && `晚间 ${fmt(b.eve)}`].filter(Boolean).join(' · ')}
                  {`（${(d.activities || []).length} 项）`}
                </span>
              </div>
            );
          })}
          {days.length === 0 && <div className="text-[12px] text-ink-400">暂无每日明细</div>}
        </div>

        {/* 政策预警条：提交前提示违例，可「仍然提交」（PRD v2 §8） */}
        {showPolicyWarn && (
          <div className="flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2 text-[12px] text-amber-700">
            <AlertTriangle size={14} className="shrink-0 mt-px" />
            <span>政策预警：{policy.content || '存在超标准项，请确认后提交'}</span>
          </div>
        )}

        {/* 操作区 */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            onClick={() => onConfirm?.(applyChoices(trip, hotels[hotelIdx], transport))}
            disabled={busy}
            className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-xl bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            确认并提交审批
          </button>
          <button
            onClick={onEdit}
            disabled={busy}
            className="flex items-center gap-1.5 px-3 py-2 text-xs rounded-xl bg-white border border-gray-200 text-ink-600 hover:border-primary-300 hover:text-primary-600 disabled:opacity-50 transition-colors"
          >
            <RotateCcw size={12} /> 改参数重新生成
          </button>
          <button
            onClick={onCancel}
            disabled={busy}
            className="flex items-center gap-1.5 px-3 py-2 text-xs rounded-xl bg-white border border-gray-200 text-ink-500 hover:border-red-200 hover:text-red-500 disabled:opacity-50 transition-colors"
          >
            <X size={12} /> 取消
          </button>
        </div>
      </div>
    </div>
  );
}

/** 把确认页的选择写回草案：酒店（替换 accommodation 活动位置）+ 交通方式，随确认提交 */
function applyChoices(trip, hotel, transport) {
  const next = JSON.parse(JSON.stringify(trip));
  next.transport = transport;
  if (hotel) {
    next.hotel_choice = { name: hotel.name, address: hotel.address || '' };
    for (const day of next.days || []) {
      for (const act of day.activities || []) {
        if (act.type === 'accommodation' && act.location?.name !== hotel.name) {
          act.location = { ...(act.location || {}), name: hotel.name, address: hotel.address || '' };
          act.tips = (act.tips || '') + '（确认页选定）';
        }
      }
    }
  }
  return next;
}
