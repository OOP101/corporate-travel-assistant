/**
 * 导航信息架构（单一来源）
 *
 * 结构参考主流 B 端产品（Linear / Vercel / Stripe Dashboard）的侧边栏分层：
 *   1. 中控台（置顶单列）—— 落地页：待办 + 全局概览 + 快捷入口
 *   2. 主工作区（常显，4 项）—— 去掉分组标题，紧跟中控台
 *   3. 企业管理（可折叠分组，管理员可见）—— 低频后台入口收进来，默认展开
 *   4. 账户区（下沉到底部用户菜单）—— 我的档案 / 系统管理 / 退出登录
 *   5. 全局跳转（⌘K 命令面板）—— 承载"想不起来在哪"的入口，见 CommandPalette
 *
 * 新增页面只需在此登记 + 在 App.jsx 注册路由。
 */
import {
  LayoutDashboard, MessageSquare, Map, Bell, Building2, FileText, CheckCircle,
  Wallet, BarChart3, Settings, BookOpen, Copy, UserCircle,
} from 'lucide-react';

/** 置顶项：登录后的落地页 */
export const HOME_ITEM = {
  to: '/',
  icon: LayoutDashboard,
  label: '中控台',
  desc: '待办与全局概览',
  keywords: 'console dashboard 中控台 概览 总览 首页 待办 工作台',
};

/** 主工作区：日常真正高频的四个入口，常显、无分组标题 */
export const WORKSPACE_ITEMS = [
  { to: '/chat', icon: MessageSquare, label: '智能助手', desc: '对话式行程生成', keywords: 'chat ai 助手 对话 生成 行程规划' },
  { to: '/trips', icon: Map, label: '差旅行程', desc: '行程列表与详情', keywords: 'trip 行程 出差 列表 详情' },
  { to: '/alerts', icon: Bell, label: '实时监控', desc: '天气路况与异常提醒', keywords: 'alert 监控 提醒 天气 航班 延误 订阅' },
  { to: '/templates', icon: Copy, label: '行程模板', desc: '一次沉淀，多次复用', keywords: 'template 模板 复用 套用' },
];

/** 企业管理：管理员专属，可折叠（默认展开，用户折叠后记住选择） */
export const ENTERPRISE_GROUP = {
  id: 'enterprise',
  label: '企业管理',
  adminOnly: true,
  items: [
    { to: '/approval', icon: CheckCircle, label: '审批流转', keywords: 'approval 审批 流转 合规 待办' },
    { to: '/reimbursement', icon: Wallet, label: '报销管理', keywords: 'reimburse 报销 费用 打款 单据' },
    { to: '/reports', icon: BarChart3, label: '报表中心', keywords: 'report 报表 统计 汇总 分析 费用' },
    { to: '/org', icon: Building2, label: '组织管理', keywords: 'org 组织 部门 员工 花名册' },
    { to: '/policy', icon: FileText, label: '差旅政策', keywords: 'policy 政策 差标 标准 校验' },
    { to: '/corpus', icon: BookOpen, label: '知识语料', keywords: 'corpus 语料 知识库 文档 攻略 检索' },
  ],
};

/** 账户区：收在左下角用户菜单里，不再占用导航位 */
export const ACCOUNT_ITEMS = [
  { to: '/profile', icon: UserCircle, label: '我的档案', keywords: 'profile 档案 画像 同行人 偏好' },
  { to: '/admin', icon: Settings, label: '系统管理', adminOnly: true, keywords: 'admin 系统 设置 模型 llm 配置 密钥' },
];

/** 账户菜单项（按角色过滤） */
export function visibleAccountItems(isAdmin) {
  return ACCOUNT_ITEMS.filter((i) => !i.adminOnly || isAdmin);
}

/** 全部页面入口（扁平）：命令面板检索 + 标题解析共用 */
export function navPageIndex() {
  return [
    { ...HOME_ITEM, group: '工作台' },
    ...WORKSPACE_ITEMS.map((i) => ({ ...i, group: '工作台' })),
    ...ENTERPRISE_GROUP.items.map((i) => ({ ...i, group: ENTERPRISE_GROUP.label })),
    ...ACCOUNT_ITEMS.map((i) => ({ ...i, group: '我的' })),
  ];
}

/** 该路径属于哪个可折叠分组（用于自动展开） */
export function groupOfPath(pathname) {
  const hit = ENTERPRISE_GROUP.items.some(
    (i) => pathname === i.to || pathname.startsWith(`${i.to}/`),
  );
  return hit ? ENTERPRISE_GROUP.id : null;
}

export const pageTitles = {
  '/': { title: '中控台', sub: '待办与全局概览' },
  '/chat': { title: '智能助手', sub: '行智 · Journey Hub' },
  '/trips': { title: '差旅行程', sub: '策程 · Planner Core' },
  '/templates': { title: '行程模板', sub: '一次沉淀，多次复用' },
  '/alerts': { title: '实时监控', sub: '感知 · Sense Engine' },
  '/profile': { title: '我的档案', sub: '出行画像与常用同行人' },
  '/org': { title: '组织管理', sub: '部门与员工' },
  '/policy': { title: '差旅政策', sub: '标准、智能匹配与合规校验' },
  '/corpus': { title: '知识语料', sub: '政策文档与景点攻略' },
  '/approval': { title: '审批流转', sub: '行程审批与合规' },
  '/reimbursement': { title: '报销管理', sub: '差旅费用报销与打款' },
  '/reports': { title: '报表中心', sub: '差旅与报销汇总分析' },
  '/admin': { title: '系统管理', sub: '模型与 LLM 服务配置' },
};

/** 详情类路由（带路径参数）的动态标题 */
export function resolvePageMeta(pathname) {
  if (pageTitles[pathname]) return pageTitles[pathname];
  if (pathname.startsWith('/trips/')) return { title: '行程详情', sub: '完整日程、出行清单与费用' };
  return { title: '企业智行', sub: 'Corporate Journey Hub' };
}
