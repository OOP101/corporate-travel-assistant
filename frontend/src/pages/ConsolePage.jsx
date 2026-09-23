/**
 * 中控台 —— 登录后的落地页：我的待办 + 全公司概览 + 快捷入口
 *
 * 角色自适应：
 *   所有人   —— 我的待办（行程 / 模板 / 监控）、差旅 KPI、最近行程、实时监控、当前模型
 *   管理员   —— 追加「企业管理」六个模块的入口卡，卡内直接带该模块的规模指标
 *
 * 数据横跨 journey-hub / planner-core / sense-engine 三个服务，全部并行拉取并
 * 用 Promise.allSettled 兜底：任一来源挂掉只降级对应卡片（页面顶部给出提示），
 * 不会整页白屏。这与命令面板的降级思路一致。
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  RefreshCw, ArrowRight, MessageSquare, Plane, Banknote, Wallet, Landmark,
  Bell, CheckCircle, BarChart3, Building2, FileText, BookOpen, Cpu, MapPin,
} from 'lucide-react';
import {
  PageHeader, Card, Button, Badge, EmptyState, StatCard, SkeletonLines,
} from '../components';
import { listTrips, listTemplates } from '../api/planner';
import {
  getReportOverview, listPolicies, listPolicyDocs, listDepartments, listEmployees,
} from '../api/organization';
import { listGuides } from '../api/guides';
import { getMonitorStatus } from '../api/sense';
import { listModels, isAdmin } from '../api/auth';
import {
  TRIP_STATUS, MONITOR_STATUS, fmtMoney, fmtInt, countOf,
} from '../config/status';

/** 监控数据源枚举 → 中文 */
const SOURCE_LABELS = {
  flight: '航班',
  train: '车次',
  weather: '天气',
  traffic: '路况',
  attraction: '景点',
};

const TONE_CLS = {
  amber: 'bg-amber-50 text-amber-600',
  green: 'bg-emerald-50 text-emerald-600',
  blue: 'bg-blue-50 text-blue-600',
  purple: 'bg-purple-50 text-purple-600',
};

/**
 * 待办卡：只有「真的有事」才发亮。
 * 零值退成灰底「暂无」并隐藏箭头 —— 一屏扫过去就知道有没有待处理。
 */
function TodoCard({ icon: Icon, label, value, unit, to, tone, always, loading }) {
  const navigate = useNavigate();
  const n = Number(value ?? 0);
  const hot = !!always || n > 0;
  return (
    <button
      type="button"
      onClick={() => navigate(to)}
      className={`text-left rounded-xl border px-4 py-3.5 flex items-center gap-3 transition-colors cursor-pointer ${
        hot
          ? 'bg-white border-gray-200 hover:border-primary-300 hover:shadow-sm'
          : 'bg-gray-50/70 border-gray-100'
      }`}
    >
      <span
        className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
          hot ? TONE_CLS[tone] : 'bg-gray-100 text-gray-300'
        }`}
      >
        <Icon size={17} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[12px] text-ink-400">{label}</span>
        {loading ? (
          <span className="skeleton block h-4 w-14 mt-1" />
        ) : (
          <span className={`block text-[17px] font-semibold leading-tight ${hot ? 'text-ink-900' : 'text-ink-300'}`}>
            {hot ? (
              <>
                {fmtInt(n)}
                <span className="text-[12px] font-normal text-ink-400 ml-1">{unit}</span>
              </>
            ) : (
              '暂无'
            )}
          </span>
        )}
      </span>
      <ArrowRight size={14} className={`shrink-0 ${hot ? 'text-ink-300' : 'text-transparent'}`} />
    </button>
  );
}

function MiniStat({ label, value, unit }) {
  return (
    <div className="bg-gray-50/70 rounded-lg px-3 py-2">
      <div className="text-[11px] text-ink-400">{label}</div>
      <div className="text-[15px] font-semibold text-ink-900 tnum">
        {fmtInt(value)}
        <span className="text-[11px] font-normal text-ink-400 ml-0.5">{unit}</span>
      </div>
    </div>
  );
}

export default function ConsolePage() {
  const navigate = useNavigate();
  const admin = isAdmin();

  const [d, setD] = useState({});
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState([]);
  const [at, setAt] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    const jobs = [
      ['overview', getReportOverview],
      ['monitor', getMonitorStatus],
      ['trips', listTrips],
      ['templates', listTemplates],
      ['models', listModels],
    ];
    if (admin) {
      jobs.push(
        ['policies', listPolicies],
        ['depts', listDepartments],
        ['employees', listEmployees],
        ['policyDocs', listPolicyDocs],
        ['guides', listGuides],
      );
    }
    const settled = await Promise.allSettled(jobs.map((job) => job[1]()));
    const next = {};
    const bad = [];
    settled.forEach((r, i) => {
      if (r.status === 'fulfilled') next[jobs[i][0]] = r.value;
      else bad.push(jobs[i][0]);
    });
    setD(next);
    setFailed(bad);
    setAt(new Date());
    setLoading(false);
  }, [admin]);

  useEffect(() => { load(); }, [load]);

  // --- 派生值 ---
  const ov = d.overview || {};
  const mon = d.monitor || {};
  const tripList = d.trips?.trips || [];
  const templateList = d.templates?.templates || [];
  const modelList = d.models?.models || [];
  const defaultModel =
    modelList.find((m) => m.model_id === d.models?.default_model) || modelList[0] || null;

  const pendingApprovals = countOf(ov.approvals?.by_status?.pending);
  const pendingReimb = countOf(ov.reimbursements?.by_status?.pending);
  const tripBudget = ov.trips?.total_budget ?? 0;

  const deptCount = d.depts?.departments?.length ?? d.depts?.count ?? 0;
  const empCount = d.employees?.employees?.length ?? d.employees?.count ?? 0;
  const policyCount = d.policies?.policies?.length ?? d.policies?.count ?? 0;
  const docCount = d.policyDocs?.documents?.length ?? d.policyDocs?.count ?? 0;
  const guideCount = d.guides?.documents?.length ?? d.guides?.count ?? 0;

  const recent = [...tripList]
    .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))
    .slice(0, 5);

  // 待办按角色给：管理员看「待我审批」，普通成员看「我的行程 / 模板」
  const todos = admin
    ? [
        { icon: CheckCircle, label: '待我审批', value: pendingApprovals, unit: '单', to: '/approval', tone: 'amber' },
        { icon: Wallet, label: '待处理报销', value: pendingReimb, unit: '笔', to: '/reimbursement', tone: 'green' },
        { icon: Bell, label: '监控订阅', value: mon.subscription_count, unit: '条', to: '/alerts', tone: 'blue', always: true },
        { icon: MapPin, label: '累计提醒', value: mon.total_alerts, unit: '条', to: '/alerts', tone: 'purple', always: true },
      ]
    : [
        { icon: Plane, label: '我的行程', value: tripList.length, unit: '条', to: '/trips', tone: 'amber', always: true },
        { icon: MessageSquare, label: '行程模板', value: templateList.length, unit: '个', to: '/templates', tone: 'green', always: true },
        { icon: Bell, label: '监控订阅', value: mon.subscription_count, unit: '条', to: '/alerts', tone: 'blue', always: true },
        { icon: MapPin, label: '累计提醒', value: mon.total_alerts, unit: '条', to: '/alerts', tone: 'purple', always: true },
      ];

  const modules = [
    {
      to: '/approval', icon: CheckCircle, label: '审批流转', desc: '行程与费用审批',
      metric: pendingApprovals > 0 ? `${fmtInt(pendingApprovals)} 单待处理` : '暂无待处理',
      alert: pendingApprovals > 0,
    },
    {
      to: '/reimbursement', icon: Wallet, label: '报销管理', desc: '提交、审批与打款',
      metric: pendingReimb > 0 ? `${fmtInt(pendingReimb)} 笔待处理` : '暂无待处理',
      alert: pendingReimb > 0,
    },
    {
      to: '/reports', icon: BarChart3, label: '报表中心', desc: '部门与月度汇总',
      metric: `行程预算 ${fmtMoney(tripBudget)}`,
    },
    {
      to: '/org', icon: Building2, label: '组织管理', desc: '部门与员工',
      metric: `${fmtInt(deptCount)} 部门 · ${fmtInt(empCount)} 员工`,
    },
    {
      to: '/policy', icon: FileText, label: '差旅政策', desc: '差标匹配与合规校验',
      metric: `${fmtInt(policyCount)} 条政策`,
    },
    {
      to: '/corpus', icon: BookOpen, label: '知识语料', desc: '政策文档 + 景点攻略',
      metric: `${fmtInt(docCount)} 文档 · ${fmtInt(guideCount)} 攻略`,
    },
  ];

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="中控台"
        subtitle={at ? `数据更新于 ${at.toLocaleTimeString()}` : '我的待办 · 全公司概览 · 快捷入口'}
        actions={
          <>
            <Button type="secondary" size="sm" onClick={() => navigate('/chat')}>
              <MessageSquare size={13} /> 开始对话
            </Button>
            <Button type="secondary" size="sm" onClick={load} loading={loading}>
              <RefreshCw size={13} /> 刷新
            </Button>
          </>
        }
      />

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-6xl mx-auto space-y-4">
          {failed.length > 0 && (
            <div className="text-[12px] text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
              部分数据源暂不可用（{failed.join('、')}），相关卡片已降级显示。
            </div>
          )}

          {/* 我的待办 */}
          <div>
            <div className="text-[13px] font-semibold text-ink-900 mb-2.5">我的待办</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {todos.map((t) => (
                <TodoCard key={t.label} {...t} loading={loading} />
              ))}
            </div>
          </div>

          {/* 全公司概览 */}
          <div>
            <div className="text-[13px] font-semibold text-ink-900 mb-2.5">全公司概览</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard
                icon={<Plane size={20} />}
                label="差旅行程"
                value={`${fmtInt(ov.trips?.total)} 笔`}
                hint={`总预算 ${fmtMoney(tripBudget)}`}
                tone="primary"
              />
              <StatCard
                icon={<Banknote size={20} />}
                label="行程预算"
                value={fmtMoney(tripBudget)}
                hint="全部行程预算合计"
                tone="green"
              />
              <StatCard
                icon={<Wallet size={20} />}
                label="报销单"
                value={`${fmtInt(ov.reimbursements?.total)} 笔`}
                hint={`合计 ${fmtMoney(ov.reimbursements?.total_amount)}`}
                tone="blue"
              />
              <StatCard
                icon={<Landmark size={20} />}
                label="审批流转"
                value={`${fmtInt(ov.approvals?.total)} 单`}
                hint={`涉及金额 ${fmtMoney(ov.approvals?.total_amount)}`}
                tone="amber"
              />
            </div>
          </div>

          {/* 最近行程 + 运行状态 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-start">
            <Card
              className="lg:col-span-2"
              header="最近行程"
              headerIcon={<Plane size={15} />}
              footer={
                <button
                  type="button"
                  onClick={() => navigate('/trips')}
                  className="text-[12px] text-primary-600 hover:text-primary-700 inline-flex items-center gap-1 cursor-pointer"
                >
                  查看全部行程 <ArrowRight size={12} />
                </button>
              }
            >
              {loading && !d.trips ? (
                <SkeletonLines lines={4} />
              ) : recent.length === 0 ? (
                <EmptyState
                  icon={<Plane size={22} />}
                  title="还没有行程"
                  description="去智能助手用一句话生成，或从行程模板套用"
                  action={{ label: '开始对话', onClick: () => navigate('/chat') }}
                />
              ) : (
                <div className="divide-y divide-gray-50 -my-1">
                  {recent.map((t) => (
                    <button
                      key={t.trip_id}
                      type="button"
                      onClick={() => navigate(`/trips/${t.trip_id}`)}
                      className="w-full text-left flex items-center gap-3 py-2.5 -mx-2 px-2 rounded-lg hover:bg-gray-50/70 transition-colors cursor-pointer"
                    >
                      <span className="w-8 h-8 rounded-lg bg-primary-50 text-primary-600 flex items-center justify-center shrink-0">
                        <MapPin size={15} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-medium text-ink-900 truncate">
                          {t.title || '未命名行程'}
                        </span>
                        <span className="block text-[11px] text-ink-400 truncate">
                          {[
                            t.origin || t.destination
                              ? `${t.origin || '未定'} → ${t.destination || '未定'}`
                              : '',
                            t.start_date
                              ? `${t.start_date}${t.end_date ? ` ~ ${t.end_date}` : ''}`
                              : '',
                          ].filter(Boolean).join(' · ') || '未填写目的地与日期'}
                        </span>
                      </span>
                      <span className="text-[12px] text-ink-600 shrink-0 tnum">
                        {fmtMoney(t.budget_total)}
                      </span>
                      <Badge tone={t.status ? 'blue' : 'gray'}>
                        {TRIP_STATUS[t.status] || '未标注'}
                      </Badge>
                    </button>
                  ))}
                </div>
              )}
            </Card>

            <div className="space-y-3">
              <Card header="实时监控" headerIcon={<Bell size={15} />}>
                <div className="flex items-center justify-between">
                  <span className="text-[13px] text-ink-600">监控服务</span>
                  <Badge tone={mon.status === 'running' ? 'green' : 'gray'}>
                    {MONITOR_STATUS[mon.status] || mon.status || '未知'}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-2 mt-3">
                  <MiniStat label="订阅行程" value={mon.subscription_count} unit="条" />
                  <MiniStat label="累计提醒" value={mon.total_alerts} unit="条" />
                </div>
                <div className="mt-3">
                  <div className="text-[11px] text-ink-400 mb-1.5">活跃数据源</div>
                  <div className="flex flex-wrap gap-1.5">
                    {(mon.active_sources || []).length === 0 ? (
                      <span className="text-[11px] text-ink-300">-</span>
                    ) : (
                      mon.active_sources.map((s) => (
                        <span key={s} className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-ink-500">
                          {SOURCE_LABELS[s] || s}
                        </span>
                      ))
                    )}
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-gray-50">
                  <button
                    type="button"
                    onClick={() => navigate('/alerts')}
                    className="text-[12px] text-primary-600 hover:text-primary-700 inline-flex items-center gap-1 cursor-pointer"
                  >
                    查看监控与提醒 <ArrowRight size={12} />
                  </button>
                </div>
              </Card>

              <Card header="当前模型" headerIcon={<Cpu size={15} />}>
                {defaultModel ? (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium text-ink-900 truncate">
                        {defaultModel.label || defaultModel.model_id}
                      </span>
                      <Badge tone="primary">默认</Badge>
                    </div>
                    <div className="mt-1.5 text-[11px] font-mono text-ink-400 truncate">
                      {defaultModel.model_id}
                    </div>
                    <div className="mt-3 text-[11px] text-ink-400">
                      可选模型 {fmtInt(modelList.length)} 个
                    </div>
                  </>
                ) : (
                  <div className="text-[12px] text-ink-400">模型列表不可用</div>
                )}
              </Card>
            </div>
          </div>

          {/* 企业管理入口（管理员） */}
          {admin && (
            <div>
              <div className="text-[13px] font-semibold text-ink-900 mb-2.5">企业管理</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {modules.map((m) => (
                  <button
                    key={m.to}
                    type="button"
                    onClick={() => navigate(m.to)}
                    className="card p-4 text-left hover:shadow-md hover:border-primary-200 transition-all cursor-pointer flex items-start gap-3"
                  >
                    <span className="w-9 h-9 rounded-lg bg-primary-50 text-primary-600 flex items-center justify-center shrink-0">
                      <m.icon size={17} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-medium text-ink-900">{m.label}</span>
                      <span className="block text-[11px] text-ink-400 mt-0.5 truncate">{m.desc}</span>
                      <span className={`block text-[12px] mt-1.5 ${m.alert ? 'text-amber-600 font-medium' : 'text-ink-500'}`}>
                        {m.metric}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
