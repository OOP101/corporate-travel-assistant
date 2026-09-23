import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Copy, Trash2, Play, MapPin, Clock, RefreshCw, Tag, Layers,
} from 'lucide-react';
import { listTemplates, getTemplate, applyTemplate, deleteTemplate } from '../api/planner';
import { PageHeader, Card, Button, Badge, EmptyState, Table, Drawer, Field } from '../components';

function fmtDate(ts) {
  if (!ts) return '—';
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const dayCount = (t) => (t?.days || []).length || t?.days_count || 0;

export default function TemplatesPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tagFilter, setTagFilter] = useState('');
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [applying, setApplying] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState(null);

  const load = async (tags = tagFilter) => {
    setLoading(true);
    try {
      const res = await listTemplates(tags.trim());
      setRows(res.templates || []);
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
      setRows([]);
    }
    setLoading(false);
  };

  useEffect(() => {
    load('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDetail = async (row) => {
    setDetail(row);
    setDetailLoading(true);
    try {
      const full = await getTemplate(row.template_id);
      setDetail(full);
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setDetailLoading(false);
  };

  const remove = async (row) => {
    if (!window.confirm(`确认删除模板「${row.template_name || row.template_id}」？`)) return;
    try {
      await deleteTemplate(row.template_id);
      setNotice({ tone: 'ok', text: '模板已删除' });
      load();
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
  };

  const doApply = async (templateId, overrides) => {
    setSubmitting(true);
    try {
      const res = await applyTemplate(templateId, overrides);
      setApplying(null);
      if (res.trip_id) navigate(`/trips/${res.trip_id}`);
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setSubmitting(false);
  };

  const noticeTone = {
    ok: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    error: 'bg-red-50 text-red-700 border-red-100',
  };

  const columns = [
    {
      key: 'template_name',
      title: '模板名称',
      render: (row) => (
        <div className="min-w-0">
          <button
            type="button"
            onClick={() => openDetail(row)}
            className="text-left font-medium text-ink-900 hover:text-primary-600 transition-colors truncate block max-w-[280px]"
          >
            {row.template_name || row.title || '(未命名模板)'}
          </button>
          <div className="text-[11px] text-ink-400 mt-0.5">
            来源行程 {row.source_trip_id || '—'}
          </div>
        </div>
      ),
    },
    {
      key: 'tags',
      title: '标签',
      render: (row) =>
        (row.tags || []).length ? (
          <div className="flex flex-wrap gap-1">
            {row.tags.map((t) => (
              <span key={t} className="text-[11px] px-1.5 py-0.5 rounded bg-primary-50 text-primary-700 border border-primary-100">
                {t}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-xs text-ink-400">—</span>
        ),
    },
    {
      key: 'destination',
      title: '目的地',
      width: '150px',
      render: (row) => (
        <span className="text-[13px] text-ink-600 flex items-center gap-1">
          <MapPin size={12} className="text-ink-400" />
          {row.destination || '—'}
        </span>
      ),
    },
    {
      key: 'days',
      title: '天数',
      width: '80px',
      render: (row) => <span className="tnum text-[13px]">{dayCount(row) || '—'}</span>,
    },
    {
      key: 'created_at',
      title: '创建时间',
      width: '120px',
      render: (row) => <span className="text-xs text-ink-400 tnum">{fmtDate(row.created_at)}</span>,
    },
    {
      key: 'ops',
      title: '操作',
      width: '130px',
      align: 'right',
      render: (row) => (
        <div className="flex items-center justify-end gap-1">
          <Button type="ghost" size="xs" onClick={() => setApplying(row)}>
            <Play size={12} className="mr-1" /> 套用
          </Button>
          <button
            type="button"
            onClick={() => remove(row)}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-ink-400 hover:bg-red-50 hover:text-red-600 transition-colors"
            title="删除"
          >
            <Trash2 size={14} />
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="px-6 py-5">
      <PageHeader
        title="行程模板"
        subtitle="把跑通的行程沉淀成模板，下次同类出差一键套用"
        actions={
          <Button type="secondary" size="sm" onClick={() => load()}>
            <RefreshCw size={14} className="mr-1.5" /> 刷新
          </Button>
        }
      />

      {notice && (
        <div className={`mb-4 rounded-xl border px-4 py-2.5 text-[13px] ${noticeTone[notice.tone] || noticeTone.ok}`}>
          {notice.text}
        </div>
      )}

      <div className="flex items-center gap-2.5 mb-4">
        <div className="relative">
          <Tag size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none" />
          <input
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') load();
            }}
            placeholder="按标签过滤，如「成都,亲子」（回车）"
            className="w-[300px] pl-9 pr-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
          />
        </div>
        <Button type="secondary" size="sm" onClick={() => load()}>过滤</Button>
        {tagFilter && (
          <Button type="ghost" size="sm" onClick={() => { setTagFilter(''); load(''); }}>清除</Button>
        )}
        <span className="ml-auto text-[12px] text-ink-400">
          共 {rows.length} 个模板 · 多标签为「匹配任一」语义
        </span>
      </div>

      <Card>
        <Table
          columns={columns}
          rows={rows}
          rowKey={(row, i) => row.template_id || String(i)}
          loading={loading}
          empty={
            <EmptyState
              icon={<Copy size={22} />}
              title="还没有模板"
              description="打开任意行程详情页，点「另存为模板」即可沉淀"
              action={{ label: '去行程列表', onClick: () => navigate('/trips') }}
            />
          }
        />
      </Card>

      <Drawer
        open={!!detail}
        title={detail?.template_name || detail?.title || '模板详情'}
        subtitle={detail ? `${detail.destination || '-'} · ${dayCount(detail)} 天 · 创建于 ${fmtDate(detail.created_at)}` : ''}
        onClose={() => setDetail(null)}
        width={600}
        footer={
          detail && (
            <Button type="primary" size="sm" onClick={() => { setApplying(detail); setDetail(null); }}>
              <Play size={13} className="mr-1.5" /> 用此模板新建行程
            </Button>
          )
        }
      >
        {detailLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => <div key={i} className="skeleton h-20" />)}
          </div>
        ) : (
          <div className="space-y-5">
            {(detail?.tags || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {detail.tags.map((t) => (
                  <Badge key={t} tone="primary">{t}</Badge>
                ))}
              </div>
            )}

            <div className="grid grid-cols-3 gap-3">
              {[
                { label: '目的地', value: detail?.destination || '—' },
                { label: '天数', value: dayCount(detail) || '—' },
                { label: '预算', value: detail?.budget_total ? `¥${detail.budget_total}` : '—' },
              ].map((it) => (
                <div key={it.label} className="rounded-xl border border-gray-100 bg-gray-50/60 px-3 py-2.5">
                  <div className="text-[11px] text-ink-400">{it.label}</div>
                  <div className="text-[13px] font-medium text-ink-900 mt-0.5 truncate">{it.value}</div>
                </div>
              ))}
            </div>

            <div>
              <div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink-900 mb-3">
                <Layers size={14} className="text-primary-500" /> 模板日程骨架
              </div>
              <div className="space-y-3">
                {(detail?.days || []).map((day, i) => (
                  <div key={i} className="rounded-xl border border-gray-100 p-3.5">
                    <div className="text-[12px] font-medium text-ink-900 mb-2">
                      Day {i + 1}{day.theme ? ` · ${day.theme}` : ''}
                    </div>
                    <div className="space-y-1.5">
                      {(day.activities || []).map((a, j) => (
                        <div key={j} className="flex items-center gap-2 text-[12px] text-ink-600">
                          <Clock size={11} className="text-ink-400 shrink-0" />
                          <span className="text-ink-400 tnum w-[86px] shrink-0">
                            {a.time_start || '--:--'}{a.time_end ? `-${a.time_end}` : ''}
                          </span>
                          <span className="truncate">{a.title}</span>
                        </div>
                      ))}
                      {!(day.activities || []).length && (
                        <div className="text-[12px] text-ink-400">该日暂无活动</div>
                      )}
                    </div>
                  </div>
                ))}
                {!(detail?.days || []).length && (
                  <div className="text-[13px] text-ink-400">模板未包含行程骨架</div>
                )}
              </div>
            </div>
          </div>
        )}
      </Drawer>

      <ApplyDrawer
        template={applying}
        submitting={submitting}
        onClose={() => setApplying(null)}
        onSubmit={doApply}
      />
    </div>
  );
}

function ApplyDrawer({ template, submitting, onClose, onSubmit }) {
  const [form, setForm] = useState({ title: '', start_date: '', budget_total: '' });

  useEffect(() => {
    if (!template) return;
    setForm({
      title: template.template_name || template.title || '',
      start_date: '',
      budget_total: template.budget_total ?? '',
    });
  }, [template]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = () => {
    const overrides = {};
    if (form.title.trim()) overrides.title = form.title.trim();
    if (form.start_date) overrides.start_date = form.start_date;
    if (form.budget_total !== '' && !Number.isNaN(Number(form.budget_total))) {
      overrides.budget_total = Number(form.budget_total);
    }
    onSubmit(template.template_id, overrides);
  };

  return (
    <Drawer
      open={!!template}
      title="用模板新建行程"
      subtitle={template ? `基于「${template.template_name || template.template_id}」复制一份新行程` : ''}
      onClose={onClose}
      footer={
        <>
          <Button type="secondary" size="sm" onClick={onClose}>取消</Button>
          <Button type="primary" size="sm" loading={submitting} onClick={submit}>
            生成行程
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-primary-100 bg-primary-50/60 px-4 py-3 text-[12px] text-ink-600 leading-relaxed">
          套用会复制模板的日程骨架并生成一条**你名下**的新行程，覆盖下面填写的字段；模板本身不受影响。
        </div>
        <Field label="行程标题">
          <input
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="开始日期">
            <input
              type="date"
              value={form.start_date}
              onChange={(e) => set('start_date', e.target.value)}
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
            />
          </Field>
          <Field label="预算（元）">
            <input
              type="number"
              value={form.budget_total}
              onChange={(e) => set('budget_total', e.target.value)}
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable tnum"
            />
          </Field>
        </div>
        <p className="text-[11px] text-ink-400">
          留空则沿用模板原值。生成后可在行程详情页继续调整。
        </p>
      </div>
    </Drawer>
  );
}
