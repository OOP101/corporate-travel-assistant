import { useState, useEffect } from 'react';
import {
  CheckCircle, XCircle, Clock, AlertTriangle,
  FileText, User, Calendar, DollarSign, MessageSquare, X, Check, MapPin,
} from 'lucide-react';
import {
  listApprovals, getApproval, approveRequest, rejectRequest, cancelApproval,
} from '../api/organization';
import { PageHeader, Card, Button, Badge, EmptyState } from '../components';

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'cancelled', label: '已取消' },
];

const STATUS_CONFIG = {
  pending: { tone: 'amber', Icon: Clock, label: '待审批' },
  approved: { tone: 'green', Icon: CheckCircle, label: '已通过' },
  rejected: { tone: 'red', Icon: XCircle, label: '已拒绝' },
  cancelled: { tone: 'gray', Icon: Clock, label: '已取消' },
};

export default function ApprovalPage() {
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState('');
  const [showDetail, setShowDetail] = useState(false);
  const [selectedApproval, setSelectedApproval] = useState(null);
  const [comment, setComment] = useState('');
  const [rejectingId, setRejectingId] = useState('');
  const [rejectReason, setRejectReason] = useState('');

  const loadApprovals = async () => {
    setLoading(true);
    try {
      const res = await listApprovals({ status: filterStatus });
      setApprovals(res.approvals || []);
    } catch (err) {
      console.error('加载审批列表失败:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadApprovals();
  }, [filterStatus]);

  const handleViewDetail = async (approvalId) => {
    try {
      const detail = await getApproval(approvalId);
      setSelectedApproval(detail);
      setShowDetail(true);
      setComment('');
    } catch (err) {
      alert('获取详情失败: ' + err.message);
    }
  };

  const handleApprove = async (approvalId) => {
    if (!confirm('确定通过此审批吗？')) return;
    try {
      await approveRequest(approvalId, comment);
      setShowDetail(false);
      loadApprovals();
    } catch (err) {
      alert('审批失败: ' + err.message);
    }
  };

  const handleReject = async (approvalId) => {
    if (!comment) { alert('请输入拒绝原因'); return; }
    if (!confirm('确定拒绝此审批吗？')) return;
    try {
      await rejectRequest(approvalId, comment);
      setShowDetail(false);
      loadApprovals();
    } catch (err) {
      alert('拒绝失败: ' + err.message);
    }
  };

  const handleRejectCard = async (approvalId) => {
    if (!rejectReason.trim()) { alert('请输入拒绝原因'); return; }
    if (!confirm('确定拒绝此审批吗？')) return;
    try {
      await rejectRequest(approvalId, rejectReason.trim());
      setRejectingId('');
      setRejectReason('');
      loadApprovals();
    } catch (err) {
      alert('拒绝失败: ' + err.message);
    }
  };

  const handleCancel = async (approvalId) => {
    if (!confirm('确定取消此审批吗？')) return;
    try {
      await cancelApproval(approvalId);
      setShowDetail(false);
      loadApprovals();
    } catch (err) {
      alert('取消失败: ' + err.message);
    }
  };

  const formatDate = (timestamp) => timestamp ? new Date(timestamp * 1000).toLocaleString() : '-';
  const formatAmount = (amount) => `¥${(amount || 0).toLocaleString()}`;

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="审批流转"
        subtitle="行程费用与政策合规审批，全程留痕"
      />

      {/* 筛选 */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setFilterStatus(opt.value)}
            className={`px-3.5 py-1.5 text-sm font-medium rounded-lg transition-colors ${
              filterStatus === opt.value
                ? 'bg-primary-600 text-white shadow-sm shadow-primary-200'
                : 'bg-white text-ink-600 border border-gray-200 hover:border-primary-300'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-5xl mx-auto space-y-3">
          {loading ? (
            <div className="text-center py-14 text-ink-400">加载中...</div>
          ) : approvals.length === 0 ? (
            <Card>
              <EmptyState icon={<FileText size={22} />} title="暂无审批记录" description="行程费用超过阈值时将自动进入审批流转" />
            </Card>
          ) : (
            approvals.map((approval) => {
              const cfg = STATUS_CONFIG[approval.status] || STATUS_CONFIG.pending;
              const trip = approval.trip || {};
              const destLabel = trip.destination
                ? `前往 ${trip.destination}`
                : (trip.title || '未指定目的地');
              const tripSub = trip.title && trip.destination ? trip.title : '';
              const applicant = approval.employee?.name || approval.employee_id || '-';
              const approver = approval.approver?.name || approval.approver_id || '-';
              const isPending = approval.status === 'pending';
              const isRejecting = rejectingId === approval.approval_id;
              return (
                <div
                  key={approval.approval_id}
                  className="card p-5 card-hover"
                >
                  <div
                    className="flex items-center justify-between mb-3 cursor-pointer"
                    onClick={() => handleViewDetail(approval.approval_id)}
                  >
                    <div className="flex items-center gap-2.5">
                      <Badge tone={cfg.tone}><cfg.Icon size={11} />{cfg.label}</Badge>
                      <span className="text-xs text-ink-400">{formatDate(approval.created_at)}</span>
                    </div>
                    <span className="text-base font-semibold text-ink-900">{formatAmount(approval.total_amount)}</span>
                  </div>

                  {/* 目的地标题：替换原 trip_id 的 ID 展示 */}
                  <div
                    className="flex items-center gap-2 mb-3 cursor-pointer"
                    onClick={() => handleViewDetail(approval.approval_id)}
                  >
                    <MapPin size={15} className="text-primary-600 shrink-0" />
                    <span className="text-[15px] font-semibold text-ink-900 truncate">{destLabel}</span>
                    {tripSub && <span className="text-[13px] text-ink-500 truncate">· {tripSub}</span>}
                  </div>

                  <div
                    className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm cursor-pointer"
                    onClick={() => handleViewDetail(approval.approval_id)}
                  >
                    {[
                      { label: '申请人', value: applicant },
                      { label: '审批人', value: approver },
                      { label: '金额', value: formatAmount(approval.total_amount), strong: true },
                    ].map(({ label, value, strong }) => (
                      <div key={label} className="bg-gray-50/70 rounded-lg px-3 py-2">
                        <div className="text-[11px] text-ink-400">{label}</div>
                        <div className={`text-[13px] ${strong ? 'font-semibold text-ink-900' : 'text-ink-600'} truncate`}>{value}</div>
                      </div>
                    ))}
                  </div>

                  {approval.violations && approval.violations.length > 0 && (
                    <div className="mt-3 px-3.5 py-2.5 bg-red-50 border border-red-100 rounded-xl">
                      <div className="flex items-center gap-1.5 text-red-600 text-[13px] font-medium mb-1">
                        <AlertTriangle size={14} /> 政策违规（{approval.violations.length} 项）
                      </div>
                      {approval.violations.slice(0, 2).map((v, idx) => (
                        <p key={idx} className="text-xs text-red-500 ml-5">{v.message}</p>
                      ))}
                    </div>
                  )}

                  {/* 待审批：同意 / 拒绝直接放在卡片外侧，点击即操作 */}
                  {isPending && !isRejecting && (
                    <div className="mt-4 flex items-center justify-end gap-3">
                      <Button type="danger" onClick={(e) => { e.stopPropagation(); setRejectingId(approval.approval_id); setRejectReason(''); }}>拒绝</Button>
                      <Button type="primary" onClick={(e) => { e.stopPropagation(); handleApprove(approval.approval_id); }}>同意</Button>
                    </div>
                  )}

                  {isRejecting && (
                    <div className="mt-4 border-t border-gray-100 pt-4" onClick={(e) => e.stopPropagation()}>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1.5">
                        拒绝原因（必填）
                      </label>
                      <textarea
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable resize-y"
                        rows={2}
                        placeholder="请输入拒绝原因..."
                        autoFocus
                      />
                      <div className="flex justify-end gap-3 mt-3">
                        <Button type="secondary" onClick={() => { setRejectingId(''); setRejectReason(''); }}>取消</Button>
                        <Button type="danger" onClick={() => handleRejectCard(approval.approval_id)}>确认拒绝</Button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* 详情 */}
      {showDetail && selectedApproval && (
        <div className="fixed inset-0 bg-ink-900/40 backdrop-blur-[2px] flex items-center justify-center z-50" onClick={() => setShowDetail(false)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl p-6 max-h-[88vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-base font-semibold text-ink-900">审批详情</h2>
              <button onClick={() => setShowDetail(false)} className="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 hover:bg-gray-100">
                <X size={18} />
              </button>
            </div>

            {(() => {
              const cfg = STATUS_CONFIG[selectedApproval.status] || STATUS_CONFIG.pending;
              return <Badge tone={cfg.tone}><cfg.Icon size={11} />{cfg.label}</Badge>;
            })()}

            {(() => {
              const dt = selectedApproval.trip || {};
              const tripDetailLabel = (dt.destination ? `前往 ${dt.destination}` : (dt.title || selectedApproval.trip_id || '-'))
                + (dt.title && dt.destination ? ` · ${dt.title}` : '');
              const applicantName = selectedApproval.employee?.name || selectedApproval.employee_id || '-';
              const approverName = selectedApproval.approver?.name || selectedApproval.approver_id || '-';
              return (
                <div className="grid grid-cols-2 gap-4 mt-5">
                  {[
                    { Icon: MapPin, label: '行程', value: tripDetailLabel },
                    { Icon: DollarSign, label: '申请金额', value: formatAmount(selectedApproval.total_amount), strong: true },
                    { Icon: User, label: '申请人', value: applicantName },
                    { Icon: User, label: '审批人', value: approverName },
                    { Icon: Calendar, label: '申请时间', value: formatDate(selectedApproval.created_at) },
                    selectedApproval.approved_at && { Icon: Calendar, label: '审批时间', value: formatDate(selectedApproval.approved_at) },
                  ].filter(Boolean).map(({ Icon, label, value, strong }, idx) => (
                    <div key={idx} className="flex items-center gap-3 bg-gray-50/70 rounded-xl px-3.5 py-3">
                      <span className="w-8 h-8 rounded-lg bg-white border border-gray-100 flex items-center justify-center text-ink-400 shrink-0">
                        <Icon size={15} />
                      </span>
                      <div className="min-w-0">
                        <div className="text-[11px] text-ink-400">{label}</div>
                        <div className={`text-sm truncate ${strong ? 'font-semibold text-ink-900' : 'text-ink-600'}`}>{value}</div>
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}

            {selectedApproval.violations && selectedApproval.violations.length > 0 && (
              <div className="mt-5">
                <h3 className="font-medium text-red-600 flex items-center gap-1.5 text-sm mb-2">
                  <AlertTriangle size={15} /> 政策违规（{selectedApproval.violations.length} 项）
                </h3>
                <div className="bg-red-50 border border-red-100 rounded-xl p-3.5 space-y-2">
                  {selectedApproval.violations.map((v, idx) => (
                    <div key={idx} className="text-sm">
                      <span className="font-medium text-ink-900">{v.activity || '未知活动'}：</span>
                      <span className="text-red-600">{v.message}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {selectedApproval.remark && (
              <div className="mt-5">
                <h3 className="font-medium text-ink-700 flex items-center gap-1.5 text-sm mb-2"><MessageSquare size={15} /> 申请备注</h3>
                <div className="bg-gray-50 rounded-xl p-3.5 text-sm text-ink-600">{selectedApproval.remark}</div>
              </div>
            )}

            {selectedApproval.approver_comment && (
              <div className="mt-5">
                <h3 className="font-medium text-ink-700 flex items-center gap-1.5 text-sm mb-2"><MessageSquare size={15} /> 审批意见</h3>
                <div className="bg-gray-50 rounded-xl p-3.5 text-sm text-ink-600">{selectedApproval.approver_comment}</div>
              </div>
            )}

            {selectedApproval.status === 'pending' && (
              <div className="border-t border-gray-100 mt-5 pt-4">
                <label className="block text-[13px] font-medium text-ink-600 mb-1.5">
                  审批意见（拒绝时必填）
                </label>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable resize-y"
                  rows={3}
                  placeholder="请输入审批意见..."
                />
                <div className="flex justify-end gap-3 mt-4">
                  <Button type="secondary" onClick={() => handleCancel(selectedApproval.approval_id)}>取消审批</Button>
                  <Button type="danger" onClick={() => handleReject(selectedApproval.approval_id)}>拒绝</Button>
                  <Button type="primary" onClick={() => handleApprove(selectedApproval.approval_id)}>通过</Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
