import { useEffect, useState } from 'react';
import {
  BookOpen, FileText, Plus, Pencil, Trash2, RefreshCw, Sparkles, Database, X,
} from 'lucide-react';
import {
  listPolicyDocs, createPolicyDoc, updatePolicyDoc, deletePolicyDoc,
  searchPolicyDocs, reindexPolicyDocs,
} from '../api/organization';
import {
  listGuides, createGuide, updateGuide, deleteGuide, searchGuides, reindexGuides,
} from '../api/guides';
import {
  PageHeader, Card, Button, Badge, EmptyState, Tab, Table, Drawer,
  Field, TagInput, SearchInput, FilterSelect,
} from '../components';

// 覆盖预设与历史数据里出现过的全部分类，避免「筛选不到实际分类」
const POLICY_CATEGORIES = [
  { value: '', label: '全部分类' },
  { value: 'travel', label: '差旅标准' },
  { value: 'policy', label: '政策' },
  { value: 'expense', label: '费用报销' },
  { value: 'approval', label: '审批规则' },
  { value: 'hotel', label: '住宿' },
  { value: 'flight', label: '机票' },
  { value: 'meal', label: '餐饮' },
  { value: 'transport', label: '交通' },
  { value: 'subsidy', label: '补贴' },
  { value: 'safety', label: '安全合规' },
  { value: 'general', label: '通用' },
];

const GUIDE_CATEGORIES = [
  { value: '', label: '全部分类' },
  { value: 'attraction', label: '景点' },
  { value: 'food', label: '美食' },
  { value: 'transport', label: '市内交通' },
  { value: 'tips', label: '避坑提示' },
];

/**
 * 两条语料通道形态完全一致（CRUD + 检索 + 重建索引），差异只在语义与召回场景。
 * 用配置表驱动，一套 UI 覆盖 14 个后端端点。
 */
const CHANNELS = [
  {
    key: 'policy',
    label: '政策文档',
    icon: FileText,
    idField: 'doc_id',
    hint: '制度类语料：差旅标准、报销规则、审批口径。行程生成时按职级与场景召回，非员工也能命中通用政策。',
    categories: POLICY_CATEGORIES,
    searchPlaceholder: '语义检索，如「部门经理出差住宿标准」',
    searchArgs: ({ query, category }) => ({ query, category }),
    api: {
      list: listPolicyDocs,
      create: createPolicyDoc,
      update: updatePolicyDoc,
      remove: deletePolicyDoc,
      search: searchPolicyDocs,
      reindex: reindexPolicyDocs,
    },
  },
  {
    key: 'guide',
    label: '景点攻略',
    icon: BookOpen,
    idField: 'guide_id',
    hint: '景点内容语料：门票、建议游玩时长、预约要求、避坑提示。只在「个人出游」场景召回，商务类行程不引用。',
    categories: GUIDE_CATEGORIES,
    searchPlaceholder: '语义检索，如「成都熊猫基地要预约吗」',
    searchArgs: ({ query, category }) => ({ query, category, topK: 8 }),
    api: {
      list: listGuides,
      create: createGuide,
      update: updateGuide,
      remove: deleteGuide,
      search: searchGuides,
      reindex: reindexGuides,
    },
  },
];

export default function CorpusPage() {
  const [channelKey, setChannelKey] = useState('policy');
  const channel = CHANNELS.find((c) => c.key === channelKey);

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState('');
  const [keyword, setKeyword] = useState('');
  const [semantic, setSemantic] = useState(null);
  const [searching, setSearching] = useState(false);
  const [notice, setNotice] = useState(null);
  const [editor, setEditor] = useState(null);
  const [detail, setDetail] = useState(null);
  const [reindexing, setReindexing] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async (cat = category) => {
    setLoading(true);
    setSemantic(null);
    try {
      const res = await channel.api.list({
        category: cat || undefined,
        keyword: keyword.trim() || undefined,
      });
      setRows(res.documents || []);
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
      setRows([]);
    }
    setLoading(false);
  };

  // 切通道时重置筛选，避免拿着政策分类去查景点
  useEffect(() => {
    setCategory('');
    setKeyword('');
    setSemantic(null);
    setNotice(null);
  }, [channelKey]);

  useEffect(() => {
    load(category);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelKey, category]);

  const runSemantic = async () => {
    const q = keyword.trim();
    if (!q) {
      load();
      return;
    }
    setSearching(true);
    setNotice(null);
    try {
      const res = await channel.api.search(channel.searchArgs({ query: q, category }));
      setSemantic(res);
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setSearching(false);
  };

  const runReindex = async () => {
    setReindexing(true);
    setNotice(null);
    try {
      const res = await channel.api.reindex(false);
      setNotice({
        tone: 'ok',
        text: `索引重建完成 · 引擎 ${res.provider || '-'} · 模型 ${res.model || '-'} · 新增 ${res.indexed_new ?? 0} 条 · 已带向量 ${res.with_embedding ?? 0}/${res.total_docs ?? 0}`,
      });
      load();
    } catch (e) {
      const msg = e.message || '';
      setNotice({
        tone: 'warn',
        text: /Embedding\s*未启用|503/.test(msg)
          ? '当前未启用向量模型，检索走关键词降级路径。配置 embedding 后此按钮可建立向量索引。'
          : msg,
      });
    }
    setReindexing(false);
  };

  const submitEditor = async (form) => {
    setSaving(true);
    try {
      if (editor?.doc) {
        await channel.api.update(editor.doc[channel.idField], {
          title: form.title,
          content: form.content,
          category: form.category,
          tags: form.tags,
          source: form.source,
        });
      } else {
        await channel.api.create({
          title: form.title,
          content: form.content,
          category: form.category || channel.categories[1].value,
          tags: form.tags,
          source: form.source,
        });
      }
      setEditor(null);
      setNotice({ tone: 'ok', text: '已保存并提交索引' });
      load();
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setSaving(false);
  };

  const removeRow = async (row) => {
    const title = row.title || row[channel.idField];
    if (!window.confirm(`确认删除「${title}」？该操作会同时移除其向量索引。`)) return;
    try {
      await channel.api.remove(row[channel.idField]);
      setNotice({ tone: 'ok', text: '已删除' });
      load();
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
  };

  const noticeTone = {
    ok: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    warn: 'bg-amber-50 text-amber-700 border-amber-100',
    error: 'bg-red-50 text-red-700 border-red-100',
  };

  const columns = [
    {
      key: 'title',
      title: '标题 / 标签',
      render: (row) => (
        <div className="min-w-0">
          <button
            type="button"
            onClick={() => setDetail(row)}
            className="text-left font-medium text-ink-900 hover:text-primary-600 transition-colors truncate block max-w-[320px]"
          >
            {row.title || '(无标题)'}
          </button>
          {(row.tags || []).length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {row.tags.map((t) => (
                <span key={t} className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-ink-600">{t}</span>
              ))}
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'category',
      title: '分类',
      width: '110px',
      render: (row) => (
        <Badge tone="blue">
          {channel.categories.find((c) => c.value === row.category)?.label || row.category || '-'}
        </Badge>
      ),
    },
    {
      key: 'excerpt',
      title: '内容摘要',
      render: (row) => (
        <span className="text-ink-400 text-xs line-clamp-2 block max-w-[280px]">
          {(row.content || '').slice(0, 90) || '-'}
        </span>
      ),
    },
    {
      key: 'source',
      title: '来源',
      width: '130px',
      render: (row) => <span className="text-xs text-ink-400">{row.source || '—'}</span>,
    },
    {
      key: 'ops',
      title: '操作',
      width: '100px',
      align: 'right',
      render: (row) => (
        <div className="flex items-center justify-end gap-1">
          <button
            type="button"
            onClick={() => setEditor({ doc: row })}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-ink-400 hover:bg-primary-50 hover:text-primary-600 transition-colors"
            title="编辑"
          >
            <Pencil size={14} />
          </button>
          <button
            type="button"
            onClick={() => removeRow(row)}
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
        title="知识语料"
        subtitle="两条 RAG 通道分库管理：制度类与景点类互不污染，各自独立建索引"
        actions={
          <Button type="secondary" size="sm" loading={reindexing} onClick={runReindex}>
            <RefreshCw size={14} className="mr-1.5" /> 重建向量索引
          </Button>
        }
      />

      {notice && (
        <div className={`mb-4 flex items-start gap-2 rounded-xl border px-4 py-2.5 text-[13px] ${noticeTone[notice.tone] || noticeTone.ok}`}>
          <span className="flex-1 leading-relaxed">{notice.text}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-current opacity-60 hover:opacity-100">
            <X size={14} />
          </button>
        </div>
      )}

      <div className="mb-4">
        <Tab
          tabs={CHANNELS.map((c) => ({ label: c.label, value: c.key }))}
          defaultActive="policy"
          onChange={setChannelKey}
        />
      </div>

      <Card className="mb-4">
        <div className="flex items-start gap-2.5 text-[12px] text-ink-600 leading-relaxed">
          <Database size={14} className="text-primary-500 mt-0.5 shrink-0" />
          <span>{channel.hint}</span>
        </div>
      </Card>

      <div className="flex items-center gap-2.5 flex-wrap mb-4">
        <SearchInput
          value={keyword}
          onChange={setKeyword}
          onEnter={runSemantic}
          placeholder={channel.searchPlaceholder}
          className="w-[320px]"
        />
        <Button type="primary" size="sm" loading={searching} onClick={runSemantic}>
          <Sparkles size={14} className="mr-1.5" /> 语义检索
        </Button>
        <FilterSelect value={category} onChange={setCategory} options={channel.categories} />
        {(semantic || keyword) && (
          <Button
            type="ghost"
            size="sm"
            onClick={() => {
              setKeyword('');
              setSemantic(null);
              load('');
            }}
          >
            重置
          </Button>
        )}
        <div className="ml-auto">
          <Button type="primary" size="sm" onClick={() => setEditor({ doc: null })}>
            <Plus size={14} className="mr-1.5" /> 新增语料
          </Button>
        </div>
      </div>

      {semantic ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-[12px] text-ink-400">
            <span>
              检索「{semantic.query}」命中 {semantic.count} 条
            </span>
            <Badge tone={semantic.mode === 'vector' ? 'green' : 'amber'}>
              {semantic.mode === 'vector' ? '向量语义' : '关键词降级'}
            </Badge>
            <span>embedding：{semantic.embedding_provider || 'none'}</span>
          </div>
          {(semantic.documents || []).length === 0 ? (
            <Card>
              <EmptyState icon={<Sparkles size={22} />} title="没有命中语料" description="换个问法，或换用关键词再试" />
            </Card>
          ) : (
            semantic.documents.map((d, i) => (
              <Card key={d[channel.idField] || i} className="card-hover">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[11px] font-medium text-primary-600 bg-primary-50 border border-primary-100 rounded-full px-2 py-0.5">
                        #{i + 1}
                      </span>
                      <span className="text-sm font-semibold text-ink-900 truncate">{d.title}</span>
                      {d.category && <Badge tone="blue">{d.category}</Badge>}
                    </div>
                    <p className="text-[13px] text-ink-600 leading-relaxed whitespace-pre-wrap">
                      {(d.content || d.excerpt || '').slice(0, 400)}
                    </p>
                  </div>
                  {typeof d.score === 'number' && (
                    <span className="text-[11px] text-ink-400 whitespace-nowrap tnum">
                      相似度 {d.score.toFixed(3)}
                    </span>
                  )}
                </div>
              </Card>
            ))
          )}
        </div>
      ) : (
        <Card>
          <Table
            columns={columns}
            rows={rows}
            rowKey={(row, i) => row[channel.idField] || String(i)}
            loading={loading}
            empty={
              <EmptyState
                icon={<channel.icon size={22} />}
                title="暂无语料"
                description="新增一条语料后，行程生成会自动引用它作为事实依据"
                action={{ label: '新增语料', onClick: () => setEditor({ doc: null }) }}
              />
            }
          />
        </Card>
      )}

      <DocEditor
        open={!!editor}
        doc={editor?.doc}
        channel={channel}
        saving={saving}
        onClose={() => setEditor(null)}
        onSubmit={submitEditor}
      />

      <Drawer
        open={!!detail}
        title={detail?.title || '语料详情'}
        subtitle={detail ? `${detail.category || '-'} · ${detail.source || '未知来源'}` : ''}
        onClose={() => setDetail(null)}
        footer={
          detail && (
            <>
              <Button type="secondary" size="sm" onClick={() => { setEditor({ doc: detail }); setDetail(null); }}>
                <Pencil size={13} className="mr-1.5" /> 编辑
              </Button>
              <Button type="danger" size="sm" onClick={() => { removeRow(detail); setDetail(null); }}>
                <Trash2 size={13} className="mr-1.5" /> 删除
              </Button>
            </>
          )
        }
      >
        {detail && (
          <div className="space-y-4">
            {(detail.tags || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {detail.tags.map((t) => (
                  <span key={t} className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-ink-600">{t}</span>
                ))}
              </div>
            )}
            <div className="text-[13px] leading-relaxed text-ink-600 whitespace-pre-wrap">
              {detail.content || '（无正文）'}
            </div>
            <div className="text-[11px] text-ink-400 pt-3 border-t border-gray-100">
              语料 ID：{detail[channel.idField]} · 归属通道：{channel.label}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

function DocEditor({ open, doc, channel, saving, onClose, onSubmit }) {
  const [form, setForm] = useState({ title: '', content: '', category: '', tags: [], source: '' });

  useEffect(() => {
    if (!open) return;
    setForm({
      title: doc?.title || '',
      content: doc?.content || '',
      category: doc?.category || channel.categories[1]?.value || 'general',
      tags: doc?.tags || [],
      source: doc?.source || '',
    });
  }, [open, doc, channel]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Drawer
      open={open}
      title={doc ? '编辑语料' : '新增语料'}
      subtitle={`归属通道：${channel.label}`}
      onClose={onClose}
      width={620}
      footer={
        <>
          <Button type="secondary" size="sm" onClick={onClose}>取消</Button>
          <Button
            type="primary"
            size="sm"
            loading={saving}
            onClick={() => {
              if (!form.title.trim() || !form.content.trim()) {
                window.alert('标题与正文为必填项');
                return;
              }
              onSubmit(form);
            }}
          >
            保存并索引
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="标题" required>
          <input
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            placeholder={channel.key === 'policy' ? '如：职级差旅住宿标准' : '如：成都大熊猫繁育研究基地'}
            className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="分类">
            <select
              value={form.category}
              onChange={(e) => set('category', e.target.value)}
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable cursor-pointer"
            >
              {channel.categories.filter((c) => c.value).map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </Field>
          <Field label="来源" hint="便于追溯，可留空">
            <input
              value={form.source}
              onChange={(e) => set('source', e.target.value)}
              placeholder="如：财务部 2026 修订版"
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
            />
          </Field>
        </div>

        <Field label="标签" hint="建议包含城市名 / 关键词，关键词降级检索时按标签召回">
          <TagInput value={form.tags} onChange={(v) => set('tags', v)} />
        </Field>

        <Field label="正文" required>
          <textarea
            value={form.content}
            onChange={(e) => set('content', e.target.value)}
            rows={12}
            placeholder="写入语料原文。这段内容会被切片建立索引，行程生成时作为事实依据引用。"
            className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable resize-y leading-relaxed"
          />
        </Field>
      </div>
    </Drawer>
  );
}
