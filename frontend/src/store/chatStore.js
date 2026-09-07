/**
 * 智能助手会话全局状态 —— 跨路由切换保留对话与流式生成。
 *
 * 痛点：原 ChatPage 把对话消息放在组件局部 useState，一旦切换菜单
 * （路由变化）组件卸载，整个对话（含刚生成的行程卡片）全部丢失。
 *
 * 方案（与 TripsPage 的 generationStore 同一套路）：
 *  - 对话消息放在模块级单例，流式请求在模块作用域持续，不被卸载打断；
 *  - localStorage 快照持久化，刷新页面也能恢复最近对话；
 *  - 首次进入且无本地快照时，回放 journey-hub 服务端会话历史兜底。
 */
import { chatStream, clearSession, getSessionHistory } from '../api/journey';

const SESSION_ID = 'web-user';
const LS_KEY = 'cjh_chat_web-user';
const MAX_STORED = 60; // localStorage 只保留最近 N 条，防止膨胀

export const GREETING = {
  role: 'assistant',
  content:
    '你好！我是企业行程智能助手，可以帮你一句话规划差旅行程、安排会议与客户拜访、解答行程问题，行中还有实时提醒和应急重排。试试下面这些示例，或直接描述你的需求：',
  intent: '',
  cards: [],
  followups: [],
};

// 回答后的补充追问 —— 固定 3 条（气泡下「继续问问」与输入框上方常驻区同源）
export const FOLLOWUPS = {
  plan: ['为这个行程订阅出行监控', '这趟行程大概要花多少钱？', '如果航班延误了会怎么办？'],
  chat: ['公司差旅报销标准是什么？', '住宿标准是多少？', '出差审批流程是怎样的？'],
  manage: ['查看我的行程列表', '帮我看看最近的行程安排', '帮我改一下明天的行程'],
  emergency: ['紧急联系电话有哪些？', '证件丢失了怎么处理？', '航班取消了我该怎么办？'],
};

// 各意图候选池（含固定 3 条在内），供「换一批」随机抽取
export const FOLLOWUP_POOL = {
  plan: [
    '为这个行程订阅出行监控', '这趟行程大概要花多少钱？', '如果航班延误了会怎么办？',
    '调整行程：把第三天下午空出来', '预算偏高，帮我换成高铁方案', '再规划一条返程备用路线',
    '这趟行程符合差旅政策吗？', '给同行的同事也同步一份行程单', '把出发日期改到周五',
  ],
  chat: [
    '公司差旅报销标准是什么？', '住宿标准是多少？', '出差审批流程是怎样的？',
    '打车费用能报销吗？', '餐补标准是多少？', '出差要提前多久申请？',
    '超预算的行程怎么审批？', '机票改签费用谁承担？', '差旅可以选头等舱吗？',
  ],
  manage: [
    '查看我的行程列表', '帮我看看最近的行程安排', '帮我改一下明天的行程',
    '删除最近的一个行程', '这个行程现在什么状态？', '审批走到哪一步了？',
    '按出发日期列出我的行程', '把某天的行程改到上午',
  ],
  emergency: [
    '紧急联系电话有哪些？', '证件丢失了怎么处理？', '航班取消了我该怎么办？',
    '突发暴雨影响出行怎么办？', '行程中身体不适联系谁？', '行程变更如何通知审批人？',
    '当地紧急求助电话有哪些？', '行程取消怎么申请退款？',
  ],
};

/** 从意图池随机抽 n 条（优先扩展项、避开固定 3 条，让「换一批」有新鲜感） */
export function sampleQuick(intent, n = 3) {
  const core = FOLLOWUPS[intent] || FOLLOWUPS.chat;
  const pool = FOLLOWUP_POOL[intent] || FOLLOWUP_POOL.chat;
  const extras = pool.filter((q) => !core.includes(q));
  const source = extras.length >= n ? extras : [...new Set([...extras, ...core])];
  const arr = [...source];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr.slice(0, n);
}

// 从完整回答中提取结构化卡片
export function buildCards(content) {
  const cards = [];
  const tripMatch = content.match(/trip_[a-z0-9]+/);
  if (tripMatch) cards.push({ type: 'trip', id: tripMatch[0] });
  const policyLine = content.split('\n').find((l) => l.includes('政策检查'));
  if (policyLine) cards.push({ type: 'policy', text: policyLine.replace(/^[^\u4e00-\u9fa5A-Za-z]*/, '').trim() });
  const approvalLine = content.split('\n').find((l) => l.includes('审批'));
  if (approvalLine) cards.push({ type: 'approval', text: approvalLine.replace(/^[^\u4e00-\u9fa5A-Za-z]*/, '').trim() });
  return cards;
}

const initialState = () => ({
  sessionId: SESSION_ID,
  messages: null, // null = 尚未水合
  loading: false,
  quick: [], // 输入框上方常驻快捷建议（回答后自动置为固定 3 条）
  quickIntent: '', // quick 对应的意图
});

let state = initialState();
let activeAbort = null;
const listeners = new Set();

function persist() {
  try {
    if (Array.isArray(state.messages)) {
      localStorage.setItem(LS_KEY, JSON.stringify(state.messages.slice(-MAX_STORED)));
    }
  } catch { /* 隐私模式等场景忽略 */ }
}

function emit() {
  listeners.forEach((fn) => fn(state));
}

function patchLast(fn) {
  if (!Array.isArray(state.messages) || state.messages.length === 0) return;
  const next = [...state.messages];
  const last = next[next.length - 1];
  next[next.length - 1] = typeof fn === 'function' ? fn(last) : { ...last, ...fn };
  state.messages = next;
  persist();
  emit();
}

function finishLoading() {
  state.loading = false;
  activeAbort = null;
  persist();
  emit();
}

/** 依据最后一条 assistant 消息同步输入框上方常驻建议（水合恢复历史后调用） */
function syncQuickFromLast() {
  if (!Array.isArray(state.messages) || state.messages.length === 0) return;
  const last = state.messages[state.messages.length - 1];
  if (last && last.role === 'assistant' && (last.followups?.length || last.intent)) {
    const intent = last.intent || 'chat';
    state.quick = FOLLOWUPS[intent] || FOLLOWUPS.chat;
    state.quickIntent = intent;
  }
}

function onStreamEvent(evt) {
  if (evt.event === 'intent') {
    patchLast((m) => ({ ...m, intent: evt.content }));
  } else if (evt.event === 'progress') {
    // 生成过程提示：不进正文，仅作阶段展示
    patchLast((m) => ({ ...m, progress: evt.content }));
  } else if (evt.event === 'chunk') {
    patchLast((m) => ({ ...m, content: (m.content || '') + evt.content, progress: '' }));
  } else if (evt.event === 'respond') {
    const content = evt.content || '';
    patchLast({ content, cards: buildCards(content), progress: '' });
  } else if (evt.event === 'error') {
    patchLast({ content: `抱歉，出错了：${evt.content}`, progress: '' });
    finishLoading();
  } else if (evt.event === 'done') {
    const last = Array.isArray(state.messages) ? state.messages[state.messages.length - 1] : null;
    const intent = (last && last.intent) || 'chat';
    patchLast((m) => ({ ...m, followups: FOLLOWUPS[intent] || FOLLOWUPS.chat }));
    // 同步刷新输入框上方常驻建议（固定 3 条，可手动「换一批」随机）
    state.quick = FOLLOWUPS[intent] || FOLLOWUPS.chat;
    state.quickIntent = intent;
    finishLoading();
  }
}

/** 把服务端历史消息归一化为聊天气泡 */
function normalizeServerMsg(m) {
  const content = m.content || '';
  return {
    role: m.role === 'user' ? 'user' : 'assistant',
    content,
    intent: '',
    cards: m.role === 'user' ? [] : buildCards(content),
    followups: [],
  };
}

export const chatStore = {
  get: () => state,
  subscribe: (fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },

  /**
   * 水合：localStorage 快照 > 服务端会话历史 > 问候语。
   * 首次进入异步拉服务端；之后组件重挂载只读内存态，不重复请求。
   */
  async hydrate() {
    if (state.messages) {
      syncQuickFromLast();
      return state.messages;
    }

    // 1) 本地快照（刷新页面也能恢复）
    let saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(LS_KEY));
    } catch { /* 忽略 */ }
    if (Array.isArray(saved) && saved.length) {
      state.messages = saved;
      syncQuickFromLast();
      persist();
      emit();
      return state.messages;
    }

    // 2) 服务端会话历史兜底（进程内保留，服务重启后为空）
    let server = [];
    try {
      const res = await getSessionHistory(SESSION_ID, 20);
      server = (res.messages || []).filter((m) => m.content).map(normalizeServerMsg);
    } catch { /* 服务不可用则从问候语开始 */ }
    state.messages = [GREETING, ...server];
    syncQuickFromLast();
    persist();
    emit();
    return state.messages;
  },

  /** 发起新一轮对话（若正在生成返回 false） */
  send(text, model) {
    if (state.loading) return false;
    if (!state.messages) state.messages = [GREETING];
    state.messages = [
      ...state.messages,
      { role: 'user', content: text },
      { role: 'assistant', content: '', intent: '', cards: [], followups: [], progress: '' },
    ];
    state.loading = true;
    persist();
    emit();

    // 模块作用域持续：切菜单不中断生成，返回后继续追加
    activeAbort = chatStream(text, SESSION_ID, onStreamEvent, model);
    return true;
  },

  /** 手动中断当前生成（如出错恢复） */
  stop() {
    if (activeAbort) {
      try { activeAbort(); } catch { /* ignore */ }
      activeAbort = null;
    }
    if (state.loading) finishLoading();
  },

  /** 输入框上方建议「换一批」：按当前意图随机抽 3 条 */
  quickRandom() {
    const intent = state.quickIntent || 'chat';
    state.quick = sampleQuick(intent, 3);
    emit();
    return state.quick;
  },

  /** 清空当前会话（本地快照 + 服务端内存历史一并清，避免刷新后旧历史回放） */
  reset() {
    if (activeAbort) {
      try { activeAbort(); } catch { /* ignore */ }
    }
    activeAbort = null;
    state = initialState();
    try { localStorage.removeItem(LS_KEY); } catch { /* ignore */ }
    clearSession(SESSION_ID).catch(() => { /* 服务不可用则忽略 */ });
    emit();
  },
};
