import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Clock, MapPin, Wallet, Package, Loader2, CheckCircle2, Printer,
  Plane, Building2, Camera, Utensils, BedDouble, ShoppingBag, Coffee,
  Route, Bookmark, X,
} from 'lucide-react';
import {
  getTrip, getChecklist, generateSummary, getExpenses, getTripExportHtml,
  rerouteTrip, saveTripAsTemplate,
} from '../api/planner';
import { Tab, Badge, StatCard, Button, Drawer, Field, TagInput } from '../components';

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

const REROUTE_PRESETS = ['景点闭馆，需替换', '航班延误 2 小时', '会议时长延长', '临时增加一站'];

export default function TripDetailPage() {
  const { tripId } = useParams();
  const navigate = useNavigate();
  const [trip, setTrip] = useState(null);
  const [checklist, setChecklist] = useState(null);
  const [summary, setSummary] = useState(null);
  const [expenses, setExpenses] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('itinerary');
  const [rerouteOpen, setRerouteOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [rerouting, setRerouting] = useState(false);
  const [savingTpl, setSavingTpl] = useState(false);
  const [notice, setNotice] = useState(null);

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

  /** 应变重排：某活动变更后，后端重排受影响的后续行程 */
  const doReroute = async (changedActivity, reason) => {
    setRerouting(true);
    setNotice(null);
    try {
      const res = await rerouteTrip(tripId, changedActivity, reason);
      setNotice({ tone: 'ok', text: res.reroute_summary || res.message || '行程已重排' });
      const fresh = await getTrip(tripId);
      setTrip(fresh);
      // 重排会改动日程，已缓存的派生视图全部失效
      setChecklist(null);
      setSummary(null);
      setExpenses(null);
      setRerouteOpen(false);
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setRerouting(false);
  };

  const doSaveTemplate = async (name, tags) => {
    setSavingTpl(true);
    setNotice(null);
    try {
      await saveTripAsTemplate(tripId, name, tags);
      setNotice({ tone: 'ok', text: `已沉淀为模板「${name}」，可在「行程模板」页一键套用` });
      setTemplateOpen(false);
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setSavingTpl(false);
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

  const locked = trip.status === 'pending_approval';

  return (
    <div className="h-full flex flex-col px-6 py-5">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
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
        <button
          onClick={() => setTemplateOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[13px] rounded-lg border border-gray-200 text-ink-600 hover:bg-gray-50 hover:text-ink-900 transition-colors"
        >
          <Bookmark size={15} /> 另存为模板
        </button>
        <Button type="secondary" size="sm" onClick={() => setRerouteOpen(true)}>
          <Route size={15} className="mr-1.5" /> 应变重排
        </Button>
        {trip.status && <Badge tone={locked ? 'amber' : 'primary'}>{trip.status}</Badge>}
      </div>

      {notice && (
        <div
          className={`mb-4 flex items-start gap-2 rounded-xl border px-4 py-2.5 text-[13px] ${
            notice.tone === 'error'
              ? 'bg-red-50 text-red-700 border-red-100'
              : 'bg-emerald-50 text-emerald-700 border-emerald-100'
          }`}
        >
          <span className="flex-1 leading-relaxed">{notice.text}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-current opacity-60 hover:opacity-100">
            <X size={14} />
          </button>
        </div>
      )}

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

      <RerouteDrawer
        open={rerouteOpen}
        days={trip.days || []}
        locked={locked}
        submitting={rerouting}
        onClose={() => setRerouteOpen(false)}
        onSubmit={doReroute}
      />

      <SaveTemplateDrawer
        open={templateOpen}
        defaultName={trip.title || ''}
        destination={trip.destination || ''}
        submitting={savingTpl}
        onClose={() => setTemplateOpen(false)}
        onSubmit={doSaveTemplate}
      />
    </div>
  );
}

function RerouteDrawer({ open, days, locked, submitting, onClose, onSubmit }) {
  const [dayIdx, setDayIdx] = useState(0);
  const [actIdx, setActIdx] = useState(0);
  const [reason, setReason] = useState('');

  useEffect(() => {
    if (open) {
      setDayIdx(0);
      setActIdx(0);
      setReason('');
    }
  }, [open]);

  const activities = days[dayIdx]?.activities || [];
  const current = activities[actIdx];

  return (
    <Drawer
      open={open}
      title="应变重排"
      subtitle="指定活动变更后，由后端重新排列受影响的后续行程"
      onClose={onClose}
      footer={
        <>
          <Button type="secondary" size="sm" onClick={onClose}>取消</Button>
          <Button
            type="primary"
            size="sm"
            loading={submitting}
            disabled={locked || !current}
            onClick={() => {
              if (!current) return;
              if (!reason.trim()) {
                window.alert('请填写变更原因，重排引擎需要它来判断影响范围');
                return;
              }
              onSubmit({ ...current, day_index: dayIdx, activity_index: actIdx }, reason.trim());
            }}
          >
            执行重排
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {locked ? (
          <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-[12px] text-amber-700 leading-relaxed">
            该行程正在等待主管审批，审批通过后才能调整（后端会拒绝待审批行程的重排请求）。
          </div>
        ) : (
          <div className="rounded-xl border border-primary-100 bg-primary-50/60 px-4 py-3 text-[12px] text-ink-600 leading-relaxed">
            重排规则：景点闭馆会推荐替代方案或前移后续活动；航班延误则整体顺延；时长变更会重新对齐时间线。重排只影响本条行程。
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="日期">
            <select
              value={dayIdx}
              onChange={(e) => { setDayIdx(Number(e.target.value)); setActIdx(0); }}
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable cursor-pointer"
            >
              {days.map((d, i) => (
                <option key={i} value={i}>
                  Day {i + 1}{d.theme ? ` · ${d.theme}` : ''}
                </option>
              ))}
            </select>
          </Field>
          <Field label="变更的活动">
            <select
              value={actIdx}
              onChange={(e) => setActIdx(Number(e.target.value))}
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable cursor-pointer"
            >
              {activities.map((a, i) => (
                <option key={i} value={i}>{a.title || `活动 ${i + 1}`}</option>
              ))}
              {!activities.length && <option value={0}>该日无活动</option>}
            </select>
          </Field>
        </div>

        {current && (
          <div className="rounded-xl border border-gray-100 bg-gray-50/60 px-4 py-3">
            <div className="text-[11px] text-ink-400 mb-1">将要变更的活动</div>
            <div className="text-[13px] font-medium text-ink-900">{current.title}</div>
            <div className="text-[11px] text-ink-400 mt-0.5">
              {current.time_start || '--:--'} - {current.time_end || '--:--'}
              {current.location?.name ? ` · ${current.location.name}` : ''}
            </div>
          </div>
        )}

        <Field label="变更原因" required hint="直接影响重排策略的选择">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="如：景点临时闭馆"
            className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
          />
        </Field>

        <div className="flex flex-wrap gap-1.5">
          {REROUTE_PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setReason(p)}
              className="px-2.5 py-1 text-[11px] rounded-full bg-white border border-gray-200 text-ink-600 hover:border-primary-300 hover:text-primary-600 transition-colors"
            >
              {p}
            </button>
          ))}
        </div>
      </div>
    </Drawer>
  );
}

function SaveTemplateDrawer({ open, defaultName, destination, submitting, onClose, onSubmit }) {
  const [name, setName] = useState('');
  const [tags, setTags] = useState([]);

  useEffect(() => {
    if (!open) return;
    setName(defaultName || '');
    setTags(destination ? [destination] : []);
  }, [open, defaultName, destination]);

  return (
    <Drawer
      open={open}
      title="另存为行程模板"
      subtitle="复制当前行程快照，后续同类差旅可直接套用"
      onClose={onClose}
      footer={
        <>
          <Button type="secondary" size="sm" onClick={onClose}>取消</Button>
          <Button
            type="primary"
            size="sm"
            loading={submitting}
            onClick={() => {
              if (!name.trim()) {
                window.alert('模板名称必填');
                return;
              }
              onSubmit(name.trim(), tags);
            }}
          >
            保存模板
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="模板名称" required>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如：成都 3 日客户拜访"
            className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
          />
        </Field>
        <Field label="标签" hint="建议含城市 / 天数 / 场景，模板列表支持按标签过滤（匹配任一）">
          <TagInput value={tags} onChange={setTags} placeholder="如：成都" />
        </Field>
        <div className="text-[11px] text-ink-400">
          模板与行程相互独立：之后修改行程不会同步到模板，套用模板也会生成新的行程。
        </div>
      </div>
    </Drawer>
  );
}
