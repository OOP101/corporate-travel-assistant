/**
 * 行程生成全局状态 —— 跨路由切换保留生成进度。
 *
 * 痛点：原 TripsPage 把生成状态放在组件局部 useState，
 * 一切换菜单（路由变化）组件卸载，流式进度与最终结果一并丢失。
 * 这里用模块级单例 store 持有「当前行程生成」状态，
 * 任何已挂载页面订阅它即可；生成请求在模块作用域持续，
 * 不被组件卸载打断。
 */

const initialState = {
  status: 'idle', // idle | analyzing | generating | done | error
  query: '',
  statusText: '',
  text: '', // 流式累计的行程文本
  tripId: null,
  trip: null,
  error: null,
};

let state = { ...initialState };
const listeners = new Set();

function emit() {
  listeners.forEach((fn) => fn(state));
}

export const generationStore = {
  get: () => state,
  /** patch 可为对象，或 (prev)=>对象 的函数（用于累加流式文本） */
  set: (patch) => {
    const next = typeof patch === 'function' ? patch(state) : patch;
    state = { ...state, ...next };
    emit();
  },
  reset: () => {
    state = { ...initialState };
    emit();
  },
  subscribe: (fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};
