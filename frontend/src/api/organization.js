/**
 * 企业化能力 API —— 差旅政策、政策文档、审批流转
 *
 * ⚠️ 2026-09-25 收敛：部门 / 员工 / 报销 / 报表四组接口已随页面一起下线。
 * v3 切型删除了对应后端路由（`/departments`、`/employees`、`/reimbursements`、`/reports/*`
 * 在 `services/` 下已无实现，见 scripts/check_api_contract.py），留着这些函数只会
 * 让调用方在运行时吃 404。规划中的替代形态是 MCP。
 */
import { get, post, postEmpty, put, del } from './client';

const BASE_URL = '/api/planner';

// ============================================
// 差旅政策
// ============================================

export async function listPolicies(level = '') {
  const params = level ? `?level=${level}` : '';
  return get(`${BASE_URL}/policies${params}`);
}

export async function createPolicy(data) {
  return post(`${BASE_URL}/policies`, data);
}

export async function getPolicy(policyId) {
  return get(`${BASE_URL}/policies/${policyId}`);
}

export async function updatePolicy(policyId, data) {
  return put(`${BASE_URL}/policies/${policyId}`, data);
}

export async function deletePolicy(policyId) {
  return del(`${BASE_URL}/policies/${policyId}`);
}

export async function matchPolicy(level, cityTier = 'all') {
  return get(`${BASE_URL}/policies/match?level=${level}&city_tier=${cityTier}`);
}

export async function checkPolicyViolations(tripId, policyId) {
  return postEmpty(`${BASE_URL}/policies/check?trip_id=${tripId}&policy_id=${policyId}`);
}

// ============================================
// 政策文档
// ============================================

export async function listPolicyDocs({ category, keyword } = {}) {
  const params = new URLSearchParams();
  if (category) params.append('category', category);
  if (keyword) params.append('keyword', keyword);
  const query = params.toString();
  return get(`${BASE_URL}/policy-docs${query ? `?${query}` : ''}`);
}

export async function createPolicyDoc(data) {
  return post(`${BASE_URL}/policy-docs`, data);
}

export async function getPolicyDoc(docId) {
  return get(`${BASE_URL}/policy-docs/${docId}`);
}

export async function updatePolicyDoc(docId, data) {
  return put(`${BASE_URL}/policy-docs/${docId}`, data);
}

export async function deletePolicyDoc(docId) {
  return del(`${BASE_URL}/policy-docs/${docId}`);
}

export async function searchPolicyDocs(query, category = '') {
  return post(`${BASE_URL}/policy-docs/search`, { query, category });
}

export async function reindexPolicyDocs(force = false) {
  return postEmpty(`${BASE_URL}/policy-docs/reindex?force=${force}`);
}

// ============================================
// 审批管理
//
// 鉴权（2026-09-25 加固）：后端要求调用方声明身份，并校验「是否该单的申请人/审批人」。
// 身份由 client.js 的 authHeaders() 自动附带 Bearer；未登录时后端按 401 拒绝，
// 不会再出现「谁都能批」的情况。
// ============================================

export async function listApprovals({ employeeId, approverId, status } = {}) {
  const params = new URLSearchParams();
  if (employeeId) params.append('employee_id', employeeId);
  if (approverId) params.append('approver_id', approverId);
  if (status) params.append('status', status);
  const query = params.toString();
  return get(`${BASE_URL}/approvals${query ? `?${query}` : ''}`);
}

export async function createApproval(data) {
  return post(`${BASE_URL}/approvals`, data);
}

export async function getApproval(approvalId) {
  return get(`${BASE_URL}/approvals/${approvalId}`);
}

export async function approveRequest(approvalId, comment = '') {
  return post(`${BASE_URL}/approvals/${approvalId}/approve`, { comment });
}

export async function rejectRequest(approvalId, comment = '') {
  return post(`${BASE_URL}/approvals/${approvalId}/reject`, { comment });
}

export async function cancelApproval(approvalId) {
  return postEmpty(`${BASE_URL}/approvals/${approvalId}/cancel`);
}
