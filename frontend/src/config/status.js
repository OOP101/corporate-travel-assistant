/**
 * 状态枚举与数字格式化（单一来源）
 *
 * 后端两种口径并存，务必按值类型分支处理，否则会渲染出「已批准 [object Object]」：
 *   trips.by_status                       值 = 纯数字
 *   reimbursements / approvals.by_status  值 = { count, amount }
 *
 * 取值统一走 countOf() / amountOf()，不要自己判断类型。
 * （2026-09-25：v3 已无 by_status 聚合端点，这两个助手暂时没有调用方 —— 但聚合口径
 * 是跨模块约定，等报表能力经 MCP 接回时直接用，不重复造。报销相关的 REIMB_STATUS
 * 与实时监控的 MONITOR_STATUS 已随对应页面下线一并删除，不要凭空复活。）
 */

export const TRIP_STATUS = {
  draft: '草稿',
  planned: '已规划',
  pending_approval: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  cancelled: '已取消',
  completed: '已完成',
  unknown: '未标注',
};

export const APPROVAL_STATUS = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  cancelled: '已取消',
};

export const fmtInt = (v) => (v ?? 0).toLocaleString();

export const fmtMoney = (v) =>
  `¥${(v ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

/** 状态分布的计数：兼容 纯数字 / { count, amount } 两种口径 */
export function countOf(v) {
  if (v === null || v === undefined) return 0;
  return typeof v === 'object' ? (v.count ?? 0) : v;
}

/** 状态分布的金额：纯数字口径返回 null（避免显示成 ¥NaN） */
export function amountOf(v) {
  return v !== null && typeof v === 'object' ? (v.amount ?? null) : null;
}
