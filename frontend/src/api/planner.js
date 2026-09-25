import { get, post, postEmpty, put, del, ssePost } from './client';

// --- 行程 ---
// 身份不由前端声明：planner 从 Authorization: Bearer 解出登录用户名
// （client.js 的 authHeaders() 会自动附带）。未登录时回退到 API Key 的 workspace。
export async function listTrips() {
  return get('/api/planner/trips');
}

export async function getTrip(tripId) {
  return get(`/api/planner/trips/${tripId}`);
}

export async function deleteTrip(tripId) {
  return del(`/api/planner/trips/${tripId}`);
}

export async function updateTrip(tripId, data) {
  return put(`/api/planner/trips/${tripId}`, { data });
}

export function generateTripStream(query, preferences = {}, onChunk, params = {}) {
  // v2：params 为用户已确认的结构化参数（scene 等）；生成产物为「草案」未落库，
  // 确认后调 confirmTrip 落库 + 审批
  return ssePost('/api/planner/trips/generate', { query, preferences, params }, onChunk);
}

// S4 → S5：确认行程草案（落库 + 政策检查 + 审批发起）
export async function confirmTrip(trip) {
  return post('/api/planner/trips/confirm', { trip });
}

// --- 清单 ---
export async function getChecklist(tripId) {
  return get(`/api/planner/trips/${tripId}/checklist`);
}

// --- 总结 ---
export async function generateSummary(tripId) {
  return postEmpty(`/api/planner/trips/${tripId}/summary`);
}

// --- 消费统计 ---
export async function getExpenses(tripId) {
  return get(`/api/planner/trips/${tripId}/expenses`);
}

// --- 行程单导出（HTML，供打印 / 另存为 PDF） ---
export async function getTripExportHtml(tripId) {
  const API_KEY = import.meta.env.VITE_API_KEY || 'ak_dev_local';
  const res = await fetch(`/api/planner/trips/${tripId}/export`, {
    headers: { 'X-API-Key': API_KEY },
  });
  if (!res.ok) throw new Error('导出失败');
  return res.text();
}

// --- 用户画像（「我的档案」页；后端 core/api/profile.py）---
export async function getProfile() {
  return get('/api/planner/users/me/profile');
}

export async function updateProfile(data) {
  return put('/api/planner/users/me/profile', data);
}

// --- 应变重排（景点闭馆 / 航班延误 / 时长变更后重排后续行程）---
export async function rerouteTrip(tripId, changedActivity, reason = '') {
  return post(`/api/planner/trips/${tripId}/reroute`, {
    changed_activity: changedActivity,
    reason,
  });
}

// --- 常用同行人 ---
export async function listCompanions() {
  return get('/api/planner/users/me/companions');
}

export async function addCompanion(data) {
  // data: { name, role: 'adult'|'child'|'elder', age, notes }
  return post('/api/planner/users/me/companions', data);
}
