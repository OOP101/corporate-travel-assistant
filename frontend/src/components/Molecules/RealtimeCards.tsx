import { ReactNode } from 'react';
import {
  Sun, CloudSun, Cloud, CloudDrizzle, CloudRain, CloudRainWind, CloudLightning,
  CloudSnow, Snowflake, CloudFog, Haze, Wind, ThermometerSun, Tornado, Thermometer,
  Droplets, PlaneTakeoff, PlaneLanding, ArrowRight, TrainFront, TriangleAlert,
  Loader2, DoorOpen, Clock, RefreshCw,
} from 'lucide-react';
import { Badge, BadgeTone } from '../Atoms/Badge';

/* ------------------------------------------------------------------ *
 * 通用外壳
 * ------------------------------------------------------------------ */

interface ShellProps {
  children: ReactNode;
  /** 左侧强调色条（按严重度上色） */
  accent?: string;
  className?: string;
}

/** 卡片外壳：统一圆角/阴影/悬浮态，底部元数据自动对齐 */
const Shell = ({ children, accent, className = '' }: ShellProps) => (
  <div className={`card p-4 flex flex-col h-full relative overflow-hidden hover:shadow-md transition-shadow ${className}`}>
    {accent && <span className={`absolute left-0 top-0 bottom-0 w-[3px] ${accent}`} />}
    {children}
  </div>
);

/** 占位卡（加载中） */
export const RealtimeSkeletonCard = ({ accent }: { accent?: string }) => (
  <Shell accent={accent}>
    <div className="flex items-start justify-between gap-3">
      <div className="flex items-center gap-2">
        <div className="skeleton w-9 h-9 rounded-xl" />
        <div className="space-y-1.5">
          <div className="skeleton h-3 w-16 rounded" />
          <div className="skeleton h-2.5 w-10 rounded" />
        </div>
      </div>
    </div>
    <div className="skeleton h-8 w-20 rounded mt-4" />
    <div className="skeleton h-2.5 w-full rounded mt-5" />
  </Shell>
);

/** 失败卡 */
export const RealtimeErrorCard = ({ title, message }: { title: string; message: string }) => (
  <Shell accent="bg-red-300">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-ink-900 truncate">{title}</div>
        <div className="text-[11px] text-ink-400">查询失败</div>
      </div>
      <span className="w-9 h-9 rounded-xl bg-red-50 flex items-center justify-center shrink-0">
        <TriangleAlert size={17} className="text-red-500" />
      </span>
    </div>
    <p className="text-[12px] text-red-600 leading-relaxed mt-3 flex-1">{message || '未知错误'}</p>
    <div className="text-[11px] text-ink-400 pt-3 mt-3 border-t" style={{ borderColor: 'var(--line)' }}>
      可稍后重试
    </div>
  </Shell>
);

/** 底部「模拟数据 / 已降级」角标 —— 真实性与降级必须可见 */
const MockTag = ({ mock, degraded }: { mock?: boolean; degraded?: boolean }) => {
  if (!mock && !degraded) return null;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] ${degraded ? 'text-amber-600' : 'text-ink-400'}`}>
      {degraded && <RefreshCw size={10} />}
      {degraded ? '接口降级 · 模拟数据' : '模拟数据'}
    </span>
  );
};

const FootRow = ({ children }: { children: ReactNode }) => (
  <div
    className="flex items-center gap-3 flex-wrap text-[11px] text-ink-500 pt-3 mt-3 border-t"
    style={{ borderColor: 'var(--line)' }}
  >
    {children}
  </div>
);

const Meta = ({ icon, children }: { icon: ReactNode; children: ReactNode }) => (
  <span className="inline-flex items-center gap-1 tnum">
    {icon}
    {children}
  </span>
);

/* ------------------------------------------------------------------ *
 * 天气
 * ------------------------------------------------------------------ */

interface WeatherMeta {
  icon: any;
  text: string;
  tint: string;
  bg: string;
}

const WEATHER_META: Record<string, WeatherMeta> = {
  clear: { icon: Sun, text: '晴', tint: 'text-amber-500', bg: 'bg-amber-50' },
  cloudy: { icon: CloudSun, text: '多云', tint: 'text-slate-500', bg: 'bg-slate-50' },
  overcast: { icon: Cloud, text: '阴', tint: 'text-slate-500', bg: 'bg-slate-100' },
  light_rain: { icon: CloudDrizzle, text: '小雨', tint: 'text-sky-500', bg: 'bg-sky-50' },
  moderate_rain: { icon: CloudRain, text: '中雨', tint: 'text-blue-500', bg: 'bg-blue-50' },
  heavy_rain: { icon: CloudRainWind, text: '暴雨', tint: 'text-indigo-600', bg: 'bg-indigo-50' },
  thunderstorm: { icon: CloudLightning, text: '雷阵雨', tint: 'text-violet-600', bg: 'bg-violet-50' },
  light_snow: { icon: CloudSnow, text: '小雪', tint: 'text-cyan-500', bg: 'bg-cyan-50' },
  heavy_snow: { icon: Snowflake, text: '大雪', tint: 'text-cyan-600', bg: 'bg-cyan-50' },
  fog: { icon: CloudFog, text: '雾', tint: 'text-slate-400', bg: 'bg-slate-50' },
  haze: { icon: Haze, text: '霾', tint: 'text-stone-500', bg: 'bg-stone-50' },
  windy: { icon: Wind, text: '大风', tint: 'text-teal-500', bg: 'bg-teal-50' },
  hot: { icon: ThermometerSun, text: '高温', tint: 'text-orange-500', bg: 'bg-orange-50' },
  typhoon: { icon: Tornado, text: '台风', tint: 'text-red-600', bg: 'bg-red-50' },
};

/**
 * 天气严重度 —— 与后端 `sources/weather.py::_EXTREME_WEATHER` 保持一致，
 * 另加「气温 ≥ 37℃ 即高温预警」（后端同款补充规则）。
 * 前端只做展示提示，告警的权威判定仍在感知引擎。
 */
export function weatherSeverity(
  condition: string,
  temp: number,
): { tone: BadgeTone; label: string; accent: string } | null {
  if (condition === 'heavy_rain' || condition === 'heavy_snow' || condition === 'typhoon') {
    return { tone: 'red', label: '严重', accent: 'bg-red-400' };
  }
  if (condition === 'thunderstorm' || condition === 'windy' || condition === 'hot' || temp >= 37) {
    return { tone: 'amber', label: '预警', accent: 'bg-amber-400' };
  }
  return null;
}

interface WeatherCardProps {
  city: string;
  data?: any;
  loading?: boolean;
  error?: string;
}

export const WeatherCard = ({ city, data, loading, error }: WeatherCardProps) => {
  if (loading) return <RealtimeSkeletonCard />;
  if (error) return <RealtimeErrorCard title={city} message={error} />;

  const condition = data?.condition || 'clear';
  const meta = WEATHER_META[condition] || WEATHER_META.clear;
  const temp = data?.temp;
  const sev = typeof temp === 'number' ? weatherSeverity(condition, temp) : null;
  const Icon = meta.icon;

  return (
    <Shell accent={sev?.accent}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-9 h-9 rounded-xl ${meta.bg} flex items-center justify-center shrink-0`}>
            <Icon size={18} className={meta.tint} />
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-semibold text-ink-900 truncate">{data?.city || city}</div>
            <div className="text-[11px] text-ink-400">{meta.text || data?.text || '—'}</div>
          </div>
        </div>
        {sev && <Badge tone={sev.tone}>{sev.label}</Badge>}
      </div>

      <div className="flex items-end gap-1 mt-4">
        <span className="text-[32px] leading-none font-semibold text-ink-900 tnum">
          {typeof temp === 'number' ? temp : '—'}
        </span>
        <span className="text-[14px] text-ink-400 mb-0.5">°C</span>
      </div>

      <FootRow>
        <Meta icon={<Thermometer size={11} />}>体感 {data?.feels_like ?? '—'}°</Meta>
        <Meta icon={<Droplets size={11} />}>湿度 {data?.humidity ?? '—'}%</Meta>
        <Meta icon={<Wind size={11} />}>
          {data?.wind_dir || ''} {data?.wind_speed || ''}
        </Meta>
        <span className="ml-auto">
          <MockTag mock={data?.mock} degraded={data?.degraded} />
        </span>
      </FootRow>
    </Shell>
  );
};

/* ------------------------------------------------------------------ *
 * 航班
 * ------------------------------------------------------------------ */

const FLIGHT_STATUS: Record<string, { tone: BadgeTone; label: string; accent: string }> = {
  scheduled: { tone: 'green', label: '准点', accent: 'bg-emerald-400' },
  boarding: { tone: 'blue', label: '登机中', accent: 'bg-blue-400' },
  delayed: { tone: 'amber', label: '延误', accent: 'bg-amber-400' },
  cancelled: { tone: 'red', label: '取消', accent: 'bg-red-400' },
  landed: { tone: 'gray', label: '已到达', accent: 'bg-slate-300' },
};

interface FlightCardProps {
  flightNumber: string;
  data?: any;
  loading?: boolean;
  error?: string;
}

export const FlightCard = ({ flightNumber, data, loading, error }: FlightCardProps) => {
  if (loading) return <RealtimeSkeletonCard />;
  if (error) return <RealtimeErrorCard title={flightNumber} message={error} />;

  const st = FLIGHT_STATUS[data?.status] || { tone: 'gray' as BadgeTone, label: data?.status || '未知', accent: 'bg-slate-300' };
  const delay = data?.delay_minutes || 0;

  return (
    <Shell accent={st.accent}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] font-mono font-semibold text-ink-900 truncate">
            {data?.flight_number || flightNumber}
          </div>
          <div className="text-[11px] text-ink-400 truncate">{data?.airline || '—'}</div>
        </div>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>

      <div className="flex items-center gap-2 mt-4 text-[13px] text-ink-900 font-medium">
        <PlaneTakeoff size={14} className="text-ink-400 shrink-0" />
        <span className="truncate">{data?.origin || '?'}</span>
        <ArrowRight size={13} className="text-ink-300 shrink-0" />
        <span className="truncate">{data?.destination || '?'}</span>
        <PlaneLanding size={14} className="text-ink-400 shrink-0 ml-auto" />
      </div>

      <div className="mt-3 flex items-end gap-4">
        <div>
          <div className="text-[10px] text-ink-400 mb-0.5">计划</div>
          <div className="text-[18px] leading-none font-semibold text-ink-900 tnum">
            {data?.scheduled_departure || '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-ink-400 mb-0.5">实际</div>
          <div
            className={`text-[18px] leading-none font-semibold tnum ${
              delay > 0 ? 'text-amber-600' : data?.status === 'cancelled' ? 'text-red-600' : 'text-ink-900'
            }`}
          >
            {data?.status === 'cancelled' ? '—' : data?.actual_departure || '—'}
          </div>
        </div>
        {delay > 0 && (
          <span className="ml-auto text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded-full px-2 py-0.5">
            延误 {delay} 分钟
          </span>
        )}
      </div>

      <FootRow>
        <Meta icon={<DoorOpen size={11} />}>登机口 {data?.gate || '—'}</Meta>
        {data?.previous_gate && data.previous_gate !== data?.gate && (
          <span className="text-[11px] text-amber-600">原 {data.previous_gate}</span>
        )}
        <span className="ml-auto">
          <MockTag mock={data?.mock} degraded={data?.degraded} />
        </span>
      </FootRow>
    </Shell>
  );
};

/* ------------------------------------------------------------------ *
 * 车次
 * ------------------------------------------------------------------ */

const TRAIN_STATUS: Record<string, { tone: BadgeTone; label: string; accent: string }> = {
  normal: { tone: 'green', label: '运行正常', accent: 'bg-emerald-400' },
  soldout: { tone: 'amber', label: '无票', accent: 'bg-amber-400' },
  cancelled: { tone: 'red', label: '停运', accent: 'bg-red-400' },
  unknown: { tone: 'gray', label: '状态未知', accent: 'bg-slate-300' },
};

interface TrainQuery {
  train_code: string;
  train_from?: string;
  train_to?: string;
  train_date?: string;
}

interface TrainCardProps {
  query: TrainQuery;
  data?: any;
  loading?: boolean;
  error?: string;
}

export const TrainCard = ({ query, data, loading, error }: TrainCardProps) => {
  if (loading) return <RealtimeSkeletonCard />;
  if (error) return <RealtimeErrorCard title={query.train_code} message={error} />;

  const st = TRAIN_STATUS[data?.status] || TRAIN_STATUS.unknown;
  const hasRoute = !!(query.train_from || query.train_to);
  const route = `${query.train_from || '?'} → ${query.train_to || '?'}`;

  return (
    <Shell accent={st.accent}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <TrainFront size={14} className="text-ink-400 shrink-0" />
            <span className="text-[15px] font-mono font-semibold text-ink-900 truncate">
              {query.train_code}
            </span>
          </div>
          {hasRoute && <div className="text-[11px] text-ink-400 mt-0.5 truncate">{route}</div>}
        </div>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>

      <p className="text-[12px] text-ink-600 leading-relaxed mt-4 flex-1">
        {(data?.detail || '—').replace(/^（模拟数据）\s*/, '')}
      </p>

      <FootRow>
        <Meta icon={<Clock size={11} />}>{query.train_date || '未指定日期'}</Meta>
        <span className="ml-auto">
          <MockTag mock={data?.mock} degraded={data?.degraded} />
        </span>
      </FootRow>
    </Shell>
  );
};

/* ------------------------------------------------------------------ *
 * 汇总条
 * ------------------------------------------------------------------ */

interface SummaryProps {
  icon: ReactNode;
  title: string;
  loading: boolean;
  total: number;
  done: number;
  failed: number;
  alertCount?: number;
  onRefresh?: () => void;
  mockAll?: boolean;
}

/** 结果区顶部汇总：数量 / 进度 / 异常计数 / 重查 */
export const ResultSummary = ({
  icon, title, loading, total, done, failed, alertCount = 0, onRefresh, mockAll,
}: SummaryProps) => (
  <div className="flex items-center gap-2 flex-wrap mb-3">
    <span className="flex items-center gap-1.5 text-sm font-semibold text-ink-900">
      {icon}
      {title}
    </span>
    <span className="text-[11px] text-ink-400">
      共 {total} 项
      {loading ? ` · 查询中 ${done}/${total}` : ` · 已完成 ${total - failed}/${total}`}
    </span>
    {alertCount > 0 && <Badge tone="red">{alertCount} 项异常</Badge>}
    {!loading && failed > 0 && <Badge tone="amber">{failed} 项失败</Badge>}
    {!loading && mockAll && total > 0 && <Badge tone="gray">全部为模拟数据</Badge>}
    {onRefresh && (
      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        className="ml-auto inline-flex items-center gap-1 text-[12px] text-ink-500 hover:text-primary-600 disabled:opacity-40 transition-colors"
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
        重查
      </button>
    )}
  </div>
);
