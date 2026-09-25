/**
 * 中控台 —— 登录后的落地页：我的待办 + 概览 + 快捷入口
 *
 * 角色自适应：
 *   所有人   —— 我的待办（行程 / 审批）、概览、最近行程、当前模型
 *   管理员   —— 追加「企业管理」三个模块的入口卡，卡内直接带该模块的规模指标
 *
 * ⚠️ 2026-09-25 收敛：本页原先横跨 journey-hub / planner-core / sense-engine 三个服务
 * 并行取数，其中 `reports/overview`、`monitor/status`、`templates`、`departments`、
 * `employees` 五路在 v3 切型后已无后端实现（整块「全公司概览」与「实时监控」卡因此
 * 长期降级）。现改为**只依赖真实存在的端点**，并把原先依赖 overview 聚合的指标
 * 改为在前端由明细直接算出 —— 少一次接口，也少一处能挂掉的依赖。
 *
 * 取数仍走 Promise.allSettled：任一来源挂掉只降级对应卡片（页顶给出提示），不整页白屏。
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  RefreshCw, ArrowRight, MessageSquare, Plane, Banknote, MapPin,
  CheckCircle, FileText, BookOpen, Cpu,
} from 'lucide-react';
import {
  PageHeader, Card, Button, Badge, EmptyState, StatCard, SkeletonLines,
} from '../components';
import { listTrips } from '../api/planner';
import { listApprovals, listPolicies, listPolicyDocs } from '../api/organization';
import { listGuides } from '../api/guides';
import { listModels, isAdmin } from '../api/auth';
import { TRIP_STATUS, fmtMoney, fmtInt } from '../config/status';

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
      ['trips', listTrips],
      ['approvals', listApprovals],
      ['models', listModels],
      ['policies', listPolicies],
      ['policyDocs', listPolicyDocs],
      ['guides', listGuides],
    ];
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
  }, []);

  useEffect(() => { load(); }, [load]);

  // --- 派生值：全部由明细算出，不再依赖已不存在的聚合端点 ---
  const tripList = d.trips?.trips || [];
  const approvalList = d.approvals?.approvals || [];
  const modelList = d.models?.models || [];
  const defaultModel =
    modelList.find((m) => m.model_id === d.models?.default_model) || modelList[0] || null;

  const policyCount = d.policies?.policies?.length ?? d.policies?.count ?? 0;
  const docCount = d.policyDocs?.documents?.length ?? d.policyDocs?.count ?? 0;
  const guideCount = d.guides?.documents?.length ?? d.guides?.count ?? 0;

  const tripBudget = tripList.reduce((s, t) => s + (Number(t.budget_total) || 0), 0);
  const pendingTrip = tripList.filter((t) => t.status === 'pending_approval').length;
  const liveTrip = tripList.filter((t) => t.status === 'planned').length;
  const pendingApprovals = approvalList.filter((a) => a.status === 'pending').length;

  const recent = [...tripList]
    .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))
    .slice(0, 5);

  // 待办：只放「需要本人动手」的行程与审批四态
  const todos = [
    { icon: MapPin, label: '我的行程', value: tripList.length, unit: '条', to: '/trips', tone: 'amber', always: true },
    { icon: Plane, label: '已生效行程', value: liveTrip, unit: '条', to: '/trips', tone: 'green', always: true },
    { icon: CheckCircle, label: '待我审批', value: pendingApprovals, unit: '单', to: '/approval', tone: 'blue' },
    { icon: FileText, label: '待审批行程', value: pendingTrip, unit: '条', to: '/trips', tone: 'purple' },
  ];

  const modules = [
    {
      to: '/approval', icon: CheckCircle, label: '审批流转', desc: '行程审批与合规',
      metric: pendingApprovals > 0 ? `${fmtInt(pendingApprovals)} 单待处理` : '暂无待处理',
      alert: pendingApprovals > 0,
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
        subtitle={at ? `数据更新于 ${at.toLocaleTimeString()}` : '我的待办 · 概览 · 快捷入口'}
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

          {/* 概览 */}
          <div>
            <div className="text-[13px] font-semibold text-ink-900 mb-2.5">概览</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard
                icon={<Plane size={20} />}
                label="差旅行程"
                value={`${fmtInt(tripList.length)} 笔`}
                hint={`待审批 ${fmtInt(pendingTrip)} 笔`}
                tone="primary"
              />
              <StatCard
                icon={<Banknote size={20} />}
                label="行程预算"
                value={fmtMoney(tripBudget)}
                hint="我的行程预算合计"
                tone="green"
              />
              <StatCard
                icon={<CheckCircle size={20} />}
                label="审批单"
                value={`${fmtInt(approvalList.length)} 单`}
                hint={`待处理 ${fmtInt(pendingApprovals)} 单`}
                tone="amber"
              />
              <StatCard
                icon={<BookOpen size={20} />}
                label="知识语料"
                value={`${fmtInt(docCount + guideCount)} 篇`}
                hint={`政策文档 ${fmtInt(docCount)} · 攻略 ${fmtInt(guideCount)}`}
                tone="blue"
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
                  description="去智能助手用一句话描述出行需求，AI 帮你生成完整差旅计划"
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
