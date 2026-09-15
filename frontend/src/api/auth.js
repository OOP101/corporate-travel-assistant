import { get, post, put } from './client';

const AUTH_KEY = 'cjh_auth';

export function getAuth() {
  try {
    return JSON.parse(localStorage.getItem(AUTH_KEY)) || null;
  } catch {
    return null;
  }
}

export function saveAuth(auth) {
  localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
}

export function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
}

export function isLoggedIn() {
  return !!getAuth()?.token;
}

export function isAdmin() {
  return getAuth()?.role === 'admin';
}

// 当前登录用户的身份标识 —— 用户名即 user_id / employee_id（种子数据里
// employee_id 与登录名同值）。会话 ID、行程归属、画像都以此为准，
// 三者口径一致才不会错位。未登录时回退到演示用户。
export function currentUserId() {
  return getAuth()?.username || 'web-user';
}

export async function login(username, password) {
  const res = await post('/api/journey/auth/login', { username, password });
  saveAuth(res);
  return res;
}

// 自助注册 —— 注册成功即签发 Token（注册即登录），无需再走一次登录
export async function register(username, password) {
  const res = await post('/api/journey/auth/register', { username, password });
  saveAuth(res);
  return res;
}

export async function logout() {
  try {
    await post('/api/journey/auth/logout', {});
  } catch { /* 本地清理优先 */ }
  clearAuth();
}

// --- 模型配置（登录用户可读，管理员可改） ---
export function listModels() {
  return get('/api/journey/agent/models');
}

export function updateModels(config) {
  return put('/api/journey/admin/models', config);
}

export function getLLMConfig() {
  return get('/api/journey/admin/llm-config');
}

export function updateLLMConfig(config) {
  return put('/api/journey/admin/llm-config', config);
}
