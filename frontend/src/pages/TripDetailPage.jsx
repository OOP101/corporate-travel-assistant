import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Clock, MapPin, Wallet, Package, Loader2, CheckCircle2, Printer,
  Plane, Building2, Camera, Utensils, BedDouble, ShoppingBag, Coffee,
} from 'lucide-react';
import { getTrip, getChecklist, generateSummary, getExpenses, getTripExportHtml } from '../api/planner';
import { Tab, Badge, StatCard } from '../components';

const TYPE_META = {
  transport: { label: '交通', tone: 'blue', Icon: Plane },
  meeting: { label: '会议', tone: 'purple', Icon: Building2 },
  attraction: { label: '景点', tone: 'green', Icon: Camera },
  dining: { label: '餐饮', tone: 'amber', Icon: Utensils },
  accommodation: { label: '住宿', tone: 'primary', Icon: BedDouble },
  shopping: { label: '购物', tone: 'pink', Icon: ShoppingBag },
  rest: { label: '休息', tone: 'gray', Icon: Coffee },
  other: { label: '其他', tone: 'gray', Icon: Coffee },
};

const CATEGORY_COLORS = {
  transport: '#3b82f6', meeting: '#8b5cf6', attraction: '#10b981',
  dining: '#f59e0b', accommodation: '#4f46e5', shopping: '#ec4899',
  rest: '#94a3b8', other: '#94a3b8',
};

export default function TripDetailPage() {
  const { tripId } = useParams();
  const navigate = useNavigate();
  const [trip, setTrip] = useState(null);
  const [checklist, setChecklist] = useState(null);
  const [summary, setSummary] = useState(null);
  const [expenses, setExpenses] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('itinerary');

  useEffect(() => {
    getTrip(tripId).then((data) => { setTrip(data); setLoading(false); }).catch(() => setLoading(false));
  }, [tripId]);

  const loadChecklist = async () => {
    if (checklist) return;
    const data = await getChecklist(tripId);
    setChecklist(data.checklist || []);
  };

  const loadSummary = async () => {
    if (summary) return;
    try {
      const data = await generateSummary(tripId);
      setSummary(data.summary);
    } catch (err) {
      // 后端失败时给出错误提示，避免标签页永远转圈
      setSummary({ error: err.message || '生成失败' });
    }
  };

  const loadExpenses = async () => {
    if (expenses) return;
    const data = await getExpenses(tripId);
    setExpenses(data.expense_summary);
  };

  const exportTripSheet = async () => {
    try {
      const html = await getTripExportHtml(tripId);
      const w = window.open('', '_blank');
      if (!w) {
        alert('导出失败：请允许浏览器弹出窗口');
        return;
      }
      w.document.open();
      w.document.write(html);
      w.document.close();
      w.focus();
      setTimeout(() => w.print(), 300);
    } catch (e) {
      alert('导出失败：' + (e.message || '未知错误'));
    }
  };

  const switchTab = (t) => {
    setTab(t);
    if (t === 'checklist') loadChecklist();
    if (t === 'summary') loadSummary();
    if (t === 'expenses') loadExpenses();
  };

  if (loading) return <div className="flex justify-center py-24"><Loader2 className="animate-spin text-ink-400" size={26} /></div>;
  if (!trip) return <div className="text-center py-24 text-ink-400">行程不存在</div>;

  const totalBudget = trip.days?.reduce(
    (sum, d) => sum + (d.activities || []).reduce((s, a) => s + (a.estimated_cost || 0), 0),
    0
  );

  const maxCategory = expenses?.by_category
    ? Math.max(1, ...Object.values(expenses.by_category).filter((v) => typeof v === 'number'))
    : 1;

  return (
    <div className="h-full flex flex-col px-6 py-5">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <button onClick={() => navigate('/trips')} className="p-2 rounded-lg text-ink-400 hover:text-ink-900 hover:bg-gray-100 transition-colors">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold text-ink-900 truncate">{trip.title || '未命名行程'}</h1>
          <p className="text-[13px] text-ink-400 flex items-center gap-1.5">
            <MapPin size={12} /> {trip.destination || '-'} · {trip.start_date || '-'} ~ {trip.end_date || '-'}
            {totalBudget > 0 && <span className="font-medium text-amber-600"> · 预算 ≈ ¥{totalBudget.toFixed(0)}</span>}
          </p>
        </div>
        <button
          onClick={exportTripSheet}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[13px] rounded-lg border border-gray-200 text-ink-600 hover:bg-gray-50 hover:text-ink-900 transition-colors"
        >
          <Printer size={15} /> 导出行程单
        </button>
        {trip.status && <Badge tone="primary">{trip.status}</Badge>}
      </div>

      {/* Tabs */}
      <div className="mb-4">
        <Tab
          tabs={[
            { label: '行程安排', value: 'itinerary' },
            { label: '出行清单', value: 'checklist' },
            { label: '行程总结', value: 'summary' },
            { label: '费用明细', value: 'expenses' },
          ]}
          defaultActive="itinerary"
          onChange={switchTab}
        />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        {tab === 'itinerary' && (
          <div className="max-w-3xl mx-auto space-y-7">
            {trip.days?.map((day, i) => (
              <div key={i}>
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 rounded-full brand-mark text-white flex items-center justify-center text-xs font-semibold shadow-sm">
                    {i + 1}
                  </div>
                  <h2 className="text-sm font-semibold text-ink-900">
                    Day {i + 1}{day.theme ? ` · ${day.theme}` : ''}
                  </h2>
                </div>
                <div className="ml-4 border-l-2 border-gray-100 pl-5 space-y-2.5">
                  {day.activities?.map((act, j) => {
                    const meta = TYPE_META[act.type] || TYPE_META.other;
                    return (
                      <div key={j} className="card p-3.5 hover:border-primary-200 transition-colors">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1.5">
                              <Badge tone={meta.tone}>
                                <meta.Icon size={11} />{meta.label}
                              </Badge>
                              {(act.time_start || act.time_end) && (
                                <span className="text-xs text-ink-400 flex items-center gap-1">
                                  <Clock size={11} />{act.time_start} - {act.time_end}
                                </span>
                              )}
                            </div>
                            <h3 className="font-medium text-ink-900 text-sm">{act.title}</h3>
                            {act.location?.name && (
                              <p className="text-xs text-ink-400 flex items-center gap-1 mt-0.5">
                                <MapPin size={11} />{act.location.name}
                              </p>
                            )}
                            {act.description && <p className="text-xs text-ink-400 mt-1 leading-relaxed">{act.description}</p>}
                          </div>
                          {act.estimated_cost > 0 && (
                            <span className="text-xs font-semibold text-amber-600 whitespace-nowrap bg-amber-50 border border-amber-100 rounded-lg px-2 py-1">
                              ¥{act.estimated_cost}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
            {(!trip.days || trip.days.length === 0) && (
              <p className="text-center text-ink-400 py-14">暂无行程安排</p>
            )}
          </div>
        )}

        {tab === 'checklist' && (
          <div className="max-w-2xl mx-auto">
            {checklist ? (
              <div className="card p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Package size={16} className="text-primary-500" />
                  <span className="text-sm font-semibold text-ink-900">出行清单 · {checklist.length} 项</span>
                </div>
                <ul className="space-y-2">
                  {checklist.map((item, i) => (
                    <li key={i} className="flex items-center gap-3 bg-gray-50/70 rounded-xl px-4 py-2.5 text-sm text-ink-600">
                      <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ) : <div className="flex justify-center py-16"><Loader2 className="animate-spin text-ink-400" size={22} /></div>}
          </div>
        )}

        {tab === 'summary' && (
          <div className="max-w-2xl mx-auto space-y-4">
            {summary ? (
              typeof summary === 'string' ? (
                <div className="card p-6 text-sm leading-relaxed whitespace-pre-wrap text-ink-600">{summary}</div>
              ) : summary.error ? (
                <div className="card p-6 text-sm text-red-500">行程总结生成失败：{summary.error}（请稍后重试）</div>
              ) : (
                <>
                  <div className="card p-5">
                    <h3 className="text-sm font-semibold text-ink-900 mb-2">概览</h3>
                    <p className="text-sm leading-relaxed text-ink-600">{summary.overview || '暂无'}</p>
                  </div>

                  {(summary.daily_recap || []).length > 0 && (
                    <div className="card p-5">
                      <h3 className="text-sm font-semibold text-ink-900 mb-3">每日回顾</h3>
                      <div className="space-y-3">
                        {summary.daily_recap.map((d, i) => (
                          <div key={i} className="border-l-2 border-primary-100 pl-3">
                            <div className="flex items-center gap-2 text-sm font-medium text-ink-900">
                              <Clock size={12} className="text-ink-400" />{d.date}
                              {d.theme && <span className="text-ink-400 font-normal">· {d.theme}</span>}
                            </div>
                            {d.highlights && <p className="text-xs text-ink-600 mt-1 leading-relaxed">{d.highlights}</p>}
                            {(typeof d.completed === 'number' || typeof d.skipped === 'number') && (
                              <p className="text-xs text-ink-400 mt-0.5">
                                完成 {d.completed ?? 0} 项{typeof d.skipped === 'number' && d.skipped > 0 ? ` · 跳过 ${d.skipped} 项` : ''}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {summary.deviation_analysis && (
                    <div className="card p-5">
                      <h3 className="text-sm font-semibold text-ink-900 mb-2">偏差分析</h3>
                      <p className="text-sm leading-relaxed text-ink-600">{summary.deviation_analysis}</p>
                    </div>
                  )}

                  {summary.expense_summary && typeof summary.expense_summary.total === 'number' && (
                    <div className="card p-5">
                      <div className="flex items-center gap-2 mb-2">
                        <Wallet size={15} className="text-amber-500" />
                        <h3 className="text-sm font-semibold text-ink-900">花费统计</h3>
                      </div>
                      <div className="flex items-baseline gap-3 text-sm">
                        <span className="font-semibold text-ink-900">¥{summary.expense_summary.total.toFixed(0)}</span>
                        {typeof summary.expense_summary.budget_total === 'number' && summary.expense_summary.budget_total > 0 && (
                          <span className={`text-xs ${summary.expense_summary.budget_diff > 0 ? 'text-red-500' : 'text-emerald-500'}`}>
                            预算 ¥{summary.expense_summary.budget_total.toFixed(0)} · {summary.expense_summary.budget_diff > 0 ? `超支 ¥${summary.expense_summary.budget_diff.toFixed(0)}` : `结余 ¥${Math.abs(summary.expense_summary.budget_diff).toFixed(0)}`}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-ink-400 mt-2">分类明细见「费用明细」标签页</p>
                    </div>
                  )}
                </>
              )
            ) : <div className="flex justify-center py-16"><Loader2 className="animate-spin text-ink-400" size={22} /></div>}
          </div>
        )}

        {tab === 'expenses' && (
          <div className="max-w-2xl mx-auto">
            {expenses ? (
              <div className="space-y-4">
                <StatCard
                  icon={<Wallet size={20} />}
                  label="预估总费用（报销口径）"
                  value={`¥${(expenses.total || 0).toFixed(0)}`}
                  tone="amber"
                />
                {expenses.by_category && Object.keys(expenses.by_category).length > 0 && (
                  <div className="card p-5 space-y-4">
                    {Object.entries(expenses.by_category).map(([cat, amount]) => {
                      const meta = TYPE_META[cat] || TYPE_META.other;
                      const pct = Math.round(((amount || 0) / (expenses.total || 1)) * 100);
                      return (
                        <div key={cat}>
                          <div className="flex justify-between text-sm mb-1.5">
                            <span className="text-ink-600 flex items-center gap-1.5">
                              <span className="w-2 h-2 rounded-full" style={{ background: CATEGORY_COLORS[cat] || '#94a3b8' }} />
                              {meta.label}
                            </span>
                            <span className="font-medium text-ink-900">¥{(amount || 0).toFixed(0)} <span className="text-xs text-ink-400 font-normal">({pct}%)</span></span>
                          </div>
                          <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{ width: `${((amount || 0) / maxCategory) * 100}%`, background: CATEGORY_COLORS[cat] || '#94a3b8' }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : <div className="flex justify-center py-16"><Loader2 className="animate-spin text-ink-400" size={22} /></div>}
          </div>
        )}
      </div>
    </div>
  );
}
