/**
 * 状态枚举与数字格式化（单一来源）
 *
 * 后端两种口径并存，务必按值类型分支处理，否则会渲染出「已批准 [object Object]」：
 *   trips.by_status                       值 = 纯数字
 *   reimbursements / approvals.by_status  值 = { count, amount }
 *
 * 取值统一走 countOf() / amountOf()，不要自己判断类型。
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

export const REIMB_STATUS = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已拒绝',
  reimbursed: '已打款',
};

export const APPROVAL_STATUS = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  cancelled: '已取消',
};

export const MONITOR_STATUS = {
  running: '运行中',
  stopped: '已停止',
  idle: '空闲',
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
