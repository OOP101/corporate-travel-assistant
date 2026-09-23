import { useState, useEffect, useCallback } from 'react';
import {
  BarChart3, Plane, Banknote, Wallet, RefreshCw,
  Building2, CalendarDays, Landmark,
} from 'lucide-react';
import {
  getReportOverview, getReportByDepartment, getReportByMonth,
} from '../api/organization';
import { PageHeader, Card, Button, StatCard, EmptyState } from '../components';
import {
  TRIP_STATUS, REIMB_STATUS, APPROVAL_STATUS,
  fmtMoney, fmtInt, countOf, amountOf,
} from '../config/status';

export default function ReportsPage() {
  const [overview, setOverview] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [months, setMonths] = useState([]);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, dep, mon] = await Promise.all([
        getReportOverview(),
        getReportByDepartment(),
        getReportByMonth(),
      ]);
      setOverview(ov);
      setDepartments(dep.departments || []);
      setMonths(mon.months || []);
      setUpdatedAt(new Date());
    } catch (err) {
      console.error('加载报表失败:', err);
      alert('报表加载失败: ' + err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  /**
   * 状态分布 chip。
   *
   * 后端两种口径并存：trips.by_status 的值是纯数字，reimbursements/approvals
   * 的值是 {count, amount} 对象，故按值类型分支渲染（此前把对象直接丢给
   * fmtMoney → 页面出现「已批准 [object Object]」）。
   */
  const renderStatusChips = (byStatus, labelMap, unit = '') => {
    const entries = byStatus ? Object.entries(byStatus) : [];
    if (entries.length === 0) {
      return <div className="mt-3 text-[11px] text-ink-400">暂无数据</div>;
    }
    return (
      <div className="flex flex-wrap gap-1.5 mt-3">
        {entries.map(([k, v]) => {
          const label = labelMap[k] || k;
          const count = countOf(v);
          const amount = amountOf(v);
          return (
            <span
              key={k}
              className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-ink-500"
              title={amount != null ? `涉及金额 ${fmtMoney(amount)}` : undefined}
            >
              {label}: {fmtInt(count)}
              {unit}
              {amount != null && ` · ${fmtMoney(amount)}`}
            </span>
          );
        })}
      </div>
    );
  };

  const num = (x) => x ?? 0;

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <div className="flex items-start justify-between">
        <PageHeader title="报表中心" subtitle="差旅与报销 · 部门/月度汇总" />
        <div className="flex items-center gap-3 pt-1">
          {updatedAt && (
            <span className="text-[11px] text-ink-400">
              更新于 {updatedAt.toLocaleTimeString()}
            </span>
          )}
          <Button type="secondary" size="sm" onClick={loadAll} loading={loading}>
            <RefreshCw size={13} /> 刷新
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-6xl mx-auto space-y-4">
          {loading && !overview ? (
            <div className="text-center py-20 text-ink-400">报表计算中...</div>
          ) : !overview ? (
            <Card><EmptyState icon={<BarChart3 size={22} />} title="暂无报表数据" description="点击右上角刷新重试" /></Card>
          ) : (
            <>
              {/* KPI 卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatCard
                  icon={<Plane size={20} />}
                  label="差旅行程"
                  value={`${fmtInt(overview.trips?.total)} 笔`}
                  hint={`总预算 ${fmtMoney(overview.trips?.total_budget)}`}
                  tone="primary"
                />
                <StatCard
                  icon={<Banknote size={20} />}
                  label="行程总预算"
                  value={fmtMoney(overview.trips?.total_budget)}
                  hint="全部行程预算合计"
                  tone="green"
                />
                <StatCard
                  icon={<Wallet size={20} />}
                  label="报销单"
                  value={`${fmtInt(overview.reimbursements?.total)} 笔`}
                  hint={`合计 ${fmtMoney(overview.reimbursements?.total_amount)}`}
                  tone="blue"
                />
                <StatCard
                  icon={<Landmark size={20} />}
                  label="审批流转"
                  value={`${fmtInt(overview.approvals?.total)} 单`}
                  hint={`涉及金额 ${fmtMoney(overview.approvals?.total_amount)}`}
                  tone="amber"
                />
              </div>

              {/* 状态分布 */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Card>
                  <div className="text-[13px] font-semibold text-ink-900">行程状态分布</div>
                  {renderStatusChips(overview.trips?.by_status, TRIP_STATUS)}
                </Card>
                <Card>
                  <div className="text-[13px] font-semibold text-ink-900">报销状态分布</div>
                  {renderStatusChips(overview.reimbursements?.by_status, REIMB_STATUS, ' 笔')}
                </Card>
                <Card>
                  <div className="text-[13px] font-semibold text-ink-900">审批状态分布</div>
                  {renderStatusChips(overview.approvals?.by_status, APPROVAL_STATUS, ' 单')}
                </Card>
              </div>

              {/* 部门汇总 */}
              <Card>
                <div className="flex items-center gap-2 mb-3">
                  <Building2 size={16} className="text-primary-500" />
                  <span className="text-sm font-semibold text-ink-900">按部门汇总</span>
                  <span className="text-[11px] text-ink-400 ml-1">{departments.length} 个部门维度</span>
                </div>
                {departments.length === 0 ? (
                  <EmptyState icon={<Building2 size={22} />} title="暂无部门数据" />
                ) : (
                  <div className="overflow-x-auto -mx-5 px-5">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs text-ink-400 border-b border-gray-100">
                          <th className="py-3 pr-4 font-medium">部门</th>
                          <th className="py-3 pr-4 text-right font-medium">人数</th>
                          <th className="py-3 pr-4 text-right font-medium">行程数</th>
                          <th className="py-3 pr-4 text-right font-medium">行程预算</th>
                          <th className="py-3 pr-4 text-right font-medium">报销笔数</th>
                          <th className="py-3 pr-4 text-right font-medium">报销金额</th>
                          <th className="py-3 pr-4 text-right font-medium">已打款</th>
                          <th className="py-3 text-right font-medium">待审批</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {departments.map((d) => (
                          <tr key={d.dept_id} className="hover:bg-gray-50/60 transition-colors">
                            <td className="py-3 pr-4">
                              <span className={`font-medium ${d.dept_name === '未归属' ? 'text-ink-400' : 'text-ink-900'}`}>
                                {d.dept_name}
                              </span>
                              {d.dept_name === '未归属' && (
                                <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-ink-400">未映射员工</span>
                              )}
                            </td>
                            <td className="py-3 pr-4 text-right text-ink-600">{fmtInt(d.employee_count)}</td>
                            <td className="py-3 pr-4 text-right text-ink-600">{fmtInt(d.trip_count)}</td>
                            <td className="py-3 pr-4 text-right font-medium text-ink-900">{fmtMoney(d.trip_budget)}</td>
                            <td className="py-3 pr-4 text-right text-ink-600">{fmtInt(d.reimb_count)}</td>
                            <td className="py-3 pr-4 text-right text-ink-600">{fmtMoney(d.reimb_amount)}</td>
                            <td className="py-3 pr-4 text-right text-emerald-600 font-medium">{fmtMoney(d.reimbursed_amount)}</td>
                            <td className="py-3 text-right text-amber-600 font-medium">{fmtMoney(d.pending_amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              {/* 月度汇总 */}
              <Card>
                <div className="flex items-center gap-2 mb-3">
                  <CalendarDays size={16} className="text-primary-500" />
                  <span className="text-sm font-semibold text-ink-900">按月汇总</span>
                  <span className="text-[11px] text-ink-400 ml-1">{months.length} 个月</span>
                </div>
                {months.length === 0 ? (
                  <EmptyState icon={<CalendarDays size={22} />} title="暂无月度数据" />
                ) : (
                  <div className="overflow-x-auto -mx-5 px-5">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs text-ink-400 border-b border-gray-100">
                          <th className="py-3 pr-4 font-medium">月份</th>
                          <th className="py-3 pr-4 text-right font-medium">行程数</th>
                          <th className="py-3 pr-4 text-right font-medium">行程预算</th>
                          <th className="py-3 pr-4 text-right font-medium">报销提交</th>
                          <th className="py-3 pr-4 text-right font-medium">已打款</th>
                          <th className="py-3 text-right font-medium">待审批</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {months.map((m) => {
                          const hasReimb = num(m.reimb_submitted) > 0;
                          return (
                            <tr key={m.month} className="hover:bg-gray-50/60 transition-colors">
                              <td className="py-3 pr-4 font-medium text-ink-900">{m.month}</td>
                              <td className="py-3 pr-4 text-right text-ink-600">{fmtInt(m.trip_count)}</td>
                              <td className="py-3 pr-4 text-right text-ink-600">{fmtMoney(m.trip_budget)}</td>
                              <td className={`py-3 pr-4 text-right ${hasReimb ? 'font-medium text-ink-900' : 'text-ink-400'}`}>
                                {num(m.reimb_submitted) > 0 ? fmtMoney(m.reimb_submitted) : '-'}
                              </td>
                              <td className="py-3 pr-4 text-right text-emerald-600 font-medium">
                                {num(m.reimb_reimbursed) > 0 ? fmtMoney(m.reimb_reimbursed) : '-'}
                              </td>
                              <td className="py-3 text-right text-amber-600 font-medium">
                                {num(m.reimb_pending) > 0 ? fmtMoney(m.reimb_pending) : '-'}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
