import { useState, useEffect } from 'react';
import {
  CheckCircle, XCircle, Clock, Wallet, AlertTriangle,
  FileText, User, Calendar, DollarSign, MessageSquare, X, Send,
} from 'lucide-react';
import {
  listReimbursements, submitReimbursement,
  getReimbursement, approveReimbursement, rejectReimbursement, payReimbursement,
} from '../api/organization';
import { PageHeader, Card, Button, Badge, EmptyState } from '../components';

const STATUS_CONFIG = {
  pending: { tone: 'amber', Icon: Clock, label: '待审批' },
  approved: { tone: 'green', Icon: CheckCircle, label: '已通过' },
  rejected: { tone: 'red', Icon: XCircle, label: '已拒绝' },
  reimbursed: { tone: 'blue', Icon: Wallet, label: '已打款' },
};

const formatDate = (timestamp) => timestamp ? new Date(timestamp * 1000).toLocaleString() : '-';
const formatAmount = (amount) => `¥${(amount || 0).toLocaleString()}`;

export default function ReimbursementPage() {
  const [reimbursements, setReimbursements] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [selected, setSelected] = useState(null);
  const [comment, setComment] = useState('');

  // 提交表单
  const [form, setForm] = useState({ trip_id: '', employee_id: '', remark: '' });
  const [submitting, setSubmitting] = useState(false);

  const loadList = async () => {
    setLoading(true);
    try {
      const res = await listReimbursements({});
      setReimbursements(res.reimbursements || []);
    } catch (err) {
      console.error('加载报销列表失败:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadList(); }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.trip_id.trim() || !form.employee_id.trim()) {
      alert('请填写行程 ID 与员工 ID');
      return;
    }
    setSubmitting(true);
    try {
      await submitReimbursement({
        trip_id: form.trip_id.trim(),
        employee_id: form.employee_id.trim(),
        remark: form.remark.trim(),
      });
      alert('报销单已提交，审批人将自动指派为员工直属主管');
      setForm({ trip_id: '', employee_id: '', remark: '' });
      loadList();
    } catch (err) {
      alert('提交失败: ' + err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleViewDetail = async (rid) => {
    try {
      const detail = await getReimbursement(rid);
      setSelected(detail);
      setShowDetail(true);
      setComment('');
    } catch (err) {
      alert('获取详情失败: ' + err.message);
    }
  };

  const handleApprove = async (rid) => {
    if (!confirm('确定通过此报销单吗？')) return;
    try {
      await approveReimbursement(rid, comment);
      setShowDetail(false);
      loadList();
    } catch (err) {
      alert('审批失败: ' + err.message);
    }
  };

  const handleReject = async (rid) => {
    if (!comment) { alert('请输入拒绝原因'); return; }
    if (!confirm('确定拒绝此报销单吗？')) return;
    try {
      await rejectReimbursement(rid, comment);
      setShowDetail(false);
      loadList();
    } catch (err) {
      alert('拒绝失败: ' + err.message);
    }
  };

  const handlePay = async (rid) => {
    if (!confirm('确定标记为已打款吗？')) return;
    try {
      await payReimbursement(rid, '');
      setShowDetail(false);
      loadList();
    } catch (err) {
      alert('打款失败: ' + err.message);
    }
  };

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader title="报销管理" subtitle="差旅费用报销提交、审批与打款全流程" />

      {/* 提交报销单 */}
      <Card className="mb-4">
        <div className="flex items-center gap-2 mb-3">
          <Send size={16} className="text-primary-500" />
          <span className="text-sm font-semibold text-ink-900">提交报销单</span>
        </div>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-[12px] text-ink-500 mb-1">行程 ID</label>
            <input
              value={form.trip_id}
              onChange={(e) => setForm({ ...form, trip_id: e.target.value })}
              placeholder="trip_xxx"
              className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable"
            />
          </div>
          <div>
            <label className="block text-[12px] text-ink-500 mb-1">员工 ID</label>
            <input
              value={form.employee_id}
              onChange={(e) => setForm({ ...form, employee_id: e.target.value })}
              placeholder="emp_xxx"
              className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable"
            />
          </div>
          <div className="flex gap-2">
            <input
              value={form.remark}
              onChange={(e) => setForm({ ...form, remark: e.target.value })}
              placeholder="报销说明（可选）"
              className="flex-1 px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable"
            />
            <Button type="primary" onClick={handleSubmit} disabled={submitting}>
              {submitting ? '提交中…' : '提交'}
            </Button>
          </div>
        </form>
      </Card>

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-5xl mx-auto space-y-3">
          {loading ? (
            <div className="text-center py-14 text-ink-400">加载中...</div>
          ) : reimbursements.length === 0 ? (
            <Card>
              <EmptyState icon={<Wallet size={22} />} title="暂无报销记录" description="提交差旅报销单后，将在此处跟踪审批与打款进度" />
            </Card>
          ) : (
            reimbursements.map((r) => {
              const cfg = STATUS_CONFIG[r.status] || STATUS_CONFIG.pending;
              return (
                <div
                  key={r.reimbursement_id}
                  className="card p-5 card-hover cursor-pointer"
                  onClick={() => handleViewDetail(r.reimbursement_id)}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2.5">
                      <Badge tone={cfg.tone}><cfg.Icon size={11} />{cfg.label}</Badge>
                      <span className="text-xs text-ink-400">{formatDate(r.created_at)}</span>
                    </div>
                    <span className="text-base font-semibold text-ink-900">{formatAmount(r.amount)}</span>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    {[
                      { label: '行程', value: (r.trip_id || '').slice(0, 14) + '...', mono: true },
                      { label: '申请人', value: r.employee_id },
                      { label: '审批人', value: r.approver_id },
                      { label: '金额', value: formatAmount(r.amount), strong: true },
                    ].map(({ label, value, mono, strong }) => (
                      <div key={label} className="bg-gray-50/70 rounded-lg px-3 py-2">
                        <div className="text-[11px] text-ink-400">{label}</div>
                        <div className={`text-[13px] ${strong ? 'font-semibold text-ink-900' : 'text-ink-600'} ${mono ? 'font-mono' : ''}`}>{value}</div>
                      </div>
                    ))}
                  </div>
                  {r.breakdown && Object.keys(r.breakdown).length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {Object.entries(r.breakdown).filter(([, v]) => v > 0).map(([k, v]) => (
                        <span key={k} className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-ink-500">
                          {k}: {formatAmount(v)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* 详情 */}
      {showDetail && selected && (
        <div className="fixed inset-0 bg-ink-900/40 backdrop-blur-[2px] flex items-center justify-center z-50" onClick={() => setShowDetail(false)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl p-6 max-h-[88vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-base font-semibold text-ink-900">报销单详情</h2>
              <button onClick={() => setShowDetail(false)} className="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 hover:bg-gray-100">
                <X size={18} />
              </button>
            </div>

            {(() => {
              const cfg = STATUS_CONFIG[selected.status] || STATUS_CONFIG.pending;
              return <Badge tone={cfg.tone}><cfg.Icon size={11} />{cfg.label}</Badge>;
            })()}

            <div className="grid grid-cols-2 gap-4 mt-5">
              {[
                { Icon: FileText, label: '报销单ID', value: selected.reimbursement_id, mono: true },
                { Icon: DollarSign, label: '报销金额', value: formatAmount(selected.amount), strong: true },
                { Icon: User, label: '申请人', value: selected.employee_id },
                { Icon: User, label: '审批人', value: selected.approver_id },
                { Icon: Calendar, label: '提交时间', value: formatDate(selected.created_at) },
                selected.approved_at && { Icon: Calendar, label: '审批时间', value: formatDate(selected.approved_at) },
                selected.paid_at && { Icon: Calendar, label: '打款时间', value: formatDate(selected.paid_at) },
              ].filter(Boolean).map(({ Icon, label, value, mono, strong }, idx) => (
                <div key={idx} className="flex items-center gap-3 bg-gray-50/70 rounded-xl px-3.5 py-3">
                  <span className="w-8 h-8 rounded-lg bg-white border border-gray-100 flex items-center justify-center text-ink-400 shrink-0">
                    <Icon size={15} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[11px] text-ink-400">{label}</div>
                    <div className={`text-sm truncate ${strong ? 'font-semibold text-ink-900' : 'text-ink-600'} ${mono ? 'font-mono' : ''}`}>{value}</div>
                  </div>
                </div>
              ))}
            </div>

            {selected.breakdown && Object.keys(selected.breakdown).length > 0 && (
              <div className="mt-5">
                <h3 className="font-medium text-ink-700 text-sm mb-2">费用构成</h3>
                <div className="bg-gray-50 rounded-xl p-3.5 space-y-1.5">
                  {Object.entries(selected.breakdown).filter(([, v]) => v > 0).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-sm">
                      <span className="text-ink-600">{k}</span>
                      <span className="font-medium text-ink-900">{formatAmount(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {selected.remark && (
              <div className="mt-5">
                <h3 className="font-medium text-ink-700 flex items-center gap-1.5 text-sm mb-2"><MessageSquare size={15} /> 报销说明</h3>
                <div className="bg-gray-50 rounded-xl p-3.5 text-sm text-ink-600">{selected.remark}</div>
              </div>
            )}

            {selected.approver_comment && (
              <div className="mt-5">
                <h3 className="font-medium text-ink-700 flex items-center gap-1.5 text-sm mb-2"><MessageSquare size={15} /> 审批意见</h3>
                <div className="bg-gray-50 rounded-xl p-3.5 text-sm text-ink-600">{selected.approver_comment}</div>
              </div>
            )}

            {selected.status === 'pending' && (
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
                  <Button type="danger" onClick={() => handleReject(selected.reimbursement_id)}>拒绝</Button>
                  <Button type="primary" onClick={() => handleApprove(selected.reimbursement_id)}>通过</Button>
                </div>
              </div>
            )}

            {selected.status === 'approved' && (
              <div className="border-t border-gray-100 mt-5 pt-4 flex justify-end">
                <Button type="primary" onClick={() => handlePay(selected.reimbursement_id)}>标记为已打款</Button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
