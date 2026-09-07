/**
 * 公共 HTTP 客户端 —— 全部 API 模块复用
 *
 * 统一 API Key、错误处理与 SSE 流式解析，避免各模块重复封装。
 */

const API_KEY = import.meta.env.VITE_API_KEY || 'ak_dev_local';

const jsonHeaders = {
  'Content-Type': 'application/json',
  'X-API-Key': API_KEY,
};

// 登录 Token（存在则附带，供 /admin/* 等接口鉴权）
function authHeaders() {
  try {
    const auth = JSON.parse(localStorage.getItem('cjh_auth'));
    if (auth?.token) return { Authorization: `Bearer ${auth.token}` };
  } catch { /* ignore */ }
  return {};
}

async function request(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: { ...jsonHeaders, ...authHeaders(), ...options.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.error || '请求失败');
  }
  return res.json();
}

export function get(url) {
  return request(url);
}

export function post(url, data) {
  return request(url, { method: 'POST', body: JSON.stringify(data) });
}

export function postEmpty(url) {
  return request(url, { method: 'POST' });
}

export function put(url, data) {
  return request(url, { method: 'PUT', body: JSON.stringify(data) });
}

export function del(url) {
  return request(url, { method: 'DELETE' });
}

/**
 * SSE 流式 POST。
 *
 * 每帧解析后回调 onEvent(frame)；收到 [DONE] 时回调 onEvent({event:'done'})；
 * 网络/HTTP 错误回调 onEvent({event:'error', content})。
 * 返回 abort 函数。
 */
export function ssePost(url, body, onEvent) {
  const controller = new AbortController();

  fetch(url, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(body),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok || !res.body) {
      let msg = res.statusText;
      try {
        const e = await res.json();
        msg = e.detail || msg;
      } catch { /* 保留 statusText */ }
      onEvent({ event: 'error', content: msg });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') {
          onEvent({ event: 'done' });
          return;
        }
        try {
          onEvent(JSON.parse(data));
        } catch { /* 忽略非 JSON 行 */ }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onEvent({ event: 'error', content: err.message });
    }
  });

  return () => controller.abort();
}
