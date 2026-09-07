/**
 * 组织管理 API —— P1 企业化功能
 *
 * 部门管理、员工管理、差旅政策、政策文档、审批流转
 */
import { get, post, postEmpty, put, del } from './client';

const BASE_URL = '/api/planner';

// ============================================
// 部门管理
// ============================================

export async function listDepartments(parentId = '') {
  const params = parentId ? `?parent_id=${parentId}` : '';
  return get(`${BASE_URL}/departments${params}`);
}

export async function createDepartment(data) {
  return post(`${BASE_URL}/departments`, data);
}

export async function getDepartment(deptId) {
  return get(`${BASE_URL}/departments/${deptId}`);
}

export async function updateDepartment(deptId, data) {
  return put(`${BASE_URL}/departments/${deptId}`, data);
}

export async function deleteDepartment(deptId) {
  return del(`${BASE_URL}/departments/${deptId}`);
}

// ============================================
// 员工管理
// ============================================

export async function listEmployees({ deptId, level, keyword } = {}) {
  const params = new URLSearchParams();
  if (deptId) params.append('dept_id', deptId);
  if (level) params.append('level', level);
  if (keyword) params.append('keyword', keyword);
  const query = params.toString();
  return get(`${BASE_URL}/employees${query ? `?${query}` : ''}`);
}

export async function createEmployee(data) {
  return post(`${BASE_URL}/employees`, data);
}

export async function getEmployee(employeeId) {
  return get(`${BASE_URL}/employees/${employeeId}`);
}

export async function updateEmployee(employeeId, data) {
  return put(`${BASE_URL}/employees/${employeeId}`, data);
}

export async function deleteEmployee(employeeId) {
  return del(`${BASE_URL}/employees/${employeeId}`);
}

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

// ============================================
// 审批管理
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

// ============================================
// 报销管理 (P2)
// ============================================

export async function listReimbursements({ employeeId, approverId, status } = {}) {
  const params = new URLSearchParams();
  if (employeeId) params.append('employee_id', employeeId);
  if (approverId) params.append('approver_id', approverId);
  if (status) params.append('status', status);
  const query = params.toString();
  return get(`${BASE_URL}/reimbursements${query ? `?${query}` : ''}`);
}

export async function submitReimbursement(data) {
  // data: { trip_id, employee_id, approver_id?, remark?, items? }
  return post(`${BASE_URL}/reimbursements`, data);
}

export async function getReimbursement(reimbursementId) {
  return get(`${BASE_URL}/reimbursements/${reimbursementId}`);
}

export async function approveReimbursement(reimbursementId, comment = '') {
  return post(`${BASE_URL}/reimbursements/${reimbursementId}/approve`, { comment });
}

export async function rejectReimbursement(reimbursementId, comment = '') {
  return post(`${BASE_URL}/reimbursements/${reimbursementId}/reject`, { comment });
}

export async function payReimbursement(reimbursementId, operator = '') {
  return post(`${BASE_URL}/reimbursements/${reimbursementId}/pay`, { operator });
}

// ============================================
// 报表中心 (P2)
// ============================================

export async function getReportOverview() {
  return get(`${BASE_URL}/reports/overview`);
}

export async function getReportByDepartment() {
  return get(`${BASE_URL}/reports/by-department`);
}

export async function getReportByMonth() {
  return get(`${BASE_URL}/reports/by-month`);
}
